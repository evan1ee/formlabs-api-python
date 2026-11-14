"""formlabs-sdk implementation of PreformPort. The ONLY module that imports the SDK (spec §3.4, rule 4).

Result-shape handling goes through `to_dict()` and is defensive. Parts marked UNVERIFIED have not been
exercised against the pinned real server (see docs/specs OD list); they are covered by the Phase 0 script
`scripts/phase0_check.py` that must be run on a machine with PreForm Server 3.64.2.3797.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from formlabs_preform_api.models import ImportUnits, OnLayoutFailure, RepairBehavior

from . import errors
from .ports import CheckResult, Device, LayoutResult, RemoteModel

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 0.5

# Warning-class checks are thresholded here and reported to the user verbatim (spec §8.5).
THIN_FEATURE_THRESHOLD_MM = 0.5


def _plain(obj: Any) -> Any:
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


def _walk_flags(value: Any) -> bool:
    """True if a per-model result reports a problem: any non-empty list or a True flag."""
    if isinstance(value, dict):
        return any(_walk_flags(v) for k, v in value.items() if k != "status")
    if isinstance(value, list):
        return len(value) > 0
    return value is True


class SdkAdapter:
    def __init__(self, preform: Any, port: int = 44388) -> None:
        """`preform` is a connected/launched sync `formlabs_sdk.PreFormApi`."""
        self._p = preform
        self._base_url = f"http://127.0.0.1:{port}"

    @classmethod
    def launch(cls, executable: str, port: int = 44388) -> tuple["SdkAdapter", Callable[[], None]]:
        """Start (Managed mode) a PreForm Server we own. Returns (adapter, close)."""
        from formlabs_sdk import FormlabsClient  # SDK import lives only in this module

        client = FormlabsClient()
        client.__enter__()
        try:
            api = client.preform.launch(executable)  # UNVERIFIED: port/args per CLI docs
        except Exception as exc:  # noqa: BLE001
            client.__exit__(None, None, None)
            raise errors.ServiceError(errors.SERVICE_START_FAILED, str(exc)) from exc
        return cls(api), lambda: client.__exit__(None, None, None)

    @classmethod
    def connect(cls, port: int = 44388) -> tuple["SdkAdapter", Callable[[], None]]:
        """Connected mode: attach to a server/PreForm window already listening. Never terminates it."""
        from formlabs_sdk import FormlabsClient

        client = FormlabsClient()
        client.__enter__()
        try:
            api = client.preform.connect()
        except Exception as exc:  # noqa: BLE001
            client.__exit__(None, None, None)
            raise errors.ServiceError(errors.SERVICE_START_FAILED, f"cannot connect on {port}: {exc}") from exc
        return cls(api), lambda: client.__exit__(None, None, None)

    def _call(self, fn: Callable[..., T], **kw: Any) -> T:
        import httpx
        from formlabs_sdk import PreFormApiError

        try:
            return fn(**kw)
        except (httpx.TransportError, ConnectionError) as exc:  # nothing is listening on the PreForm port
            raise errors.ServiceError(
                errors.PREFORM_NOT_RUNNING,
                "PreForm is not running or its server is not started. Open PreForm, start the server, then try again.",
            ) from exc
        except PreFormApiError as exc:
            raise errors.ServiceError(
                errors.PREFORM_API_ERROR,
                str(exc),
                api_code=str(getattr(exc, "code", "")),
                api_message=str(getattr(exc, "message", "")),
            ) from exc

    def _long(self, fn: Callable[..., T], **kw: Any) -> T:
        return self._call(fn, timeout=DEFAULT_TIMEOUT_S, poll_interval=POLL_INTERVAL_S, **kw)

    def server_version(self) -> str:
        return self._call(self._p.get_server_version).version

    def list_print_settings(self) -> dict[str, Any]:
        return _plain(self._call(self._p.list_print_settings))

    def validate_print_setting(self, machine_type, material_code, layer, print_setting):
        res = self._call(
            self._p.validate_print_setting,
            machine_type=machine_type,
            material_code=material_code,
            layer_thickness_mm=layer,
            print_setting=print_setting,
        )
        return bool(res.valid), _plain(res)

    def create_scene(self, machine_type, material_code, layer, print_setting) -> str:
        res = self._call(
            self._p.create_scene,
            machine_type=machine_type,
            material_code=material_code,
            layer_thickness_mm=layer,
            print_setting=print_setting,
        )
        return str(res.scene_id)

    def open_form_file(self, path: str) -> str:
        res = self._long(self._p.open_form_file, file=path)
        d = _plain(res)  # verified on 3.66.0.1146: {"project_name", "scenes": [{"scene_id", "new_model_ids", ...}]}
        ids = [x["scene_id"] for x in d.get("scenes", [])]
        if not ids:
            raise errors.ServiceError(errors.PREFORM_API_ERROR, f"open_form_file returned no scene: {d}")
        return str(ids[0])

    def save_form_file(self, scene_id: str, path: str, project_name: str = "") -> None:
        extra = {"project_name": project_name} if project_name else {}  # the name stored inside the .form file
        self._long(self._p.save_form_file, file=path, scene_ids=[scene_id], **extra)

    def delete_scene(self, scene_id: str) -> None:
        self._call(self._p.delete_scene, scene_id=scene_id)

    def import_model(self, scene_id, file, *, name, lock, units, chordal_tolerance_um, angle_tolerance_deg):
        res = self._long(
            self._p.import_models,
            scene_id=scene_id,
            file=file,
            name=name,
            lock=lock,
            units=ImportUnits(units),
            repair_behavior=RepairBehavior.ERROR,  # explicit; repairs are never silent (spec §8.1)
            chordal_tolerance_um=chordal_tolerance_um,
            angle_tolerance_deg=angle_tolerance_deg,
            split_multi_model_file=False,
        )
        return str(res.new_models[0].model_id)

    def replace_model(self, scene_id, model_id, replacement_model_id) -> None:
        self._long(
            self._p.replace_model,
            scene_id=scene_id,
            model_id=model_id,
            replacement_model_id=replacement_model_id,
        )

    def delete_models(self, scene_id, model_ids) -> None:
        self._call(self._p.delete_models, scene_id=scene_id, model_ids=model_ids)

    def scene_exists(self, scene_id) -> bool:
        """False when PreForm no longer knows the scene (it was closed or restarted)."""
        try:
            self.list_models(scene_id)
            return True
        except errors.ServiceError as exc:
            if "not found" in str(exc).lower():
                return False
            raise

    def list_models(self, scene_id) -> list[RemoteModel]:
        try:
            res = self._call(self._p.list_models, scene_id=scene_id)
            rows = [_plain(m) for m in res.models]
        except (KeyError, TypeError):
            # Server/SDK schema drift (3.66 omits fields the 3.64 wheel requires): read the raw JSON.
            rows = self._raw_models(scene_id)
        return [
            RemoteModel(
                model_id=str(m["id"]),
                name=m.get("name", ""),
                lock=str(m.get("lock", "")),
                fingerprint={
                    "bbox": m.get("bounding_box"),
                    "hash": m.get("canonical_model_hash"),
                    "raw_hash": m.get("raw_mesh_hash"),
                    "orientation": m.get("orientation"),
                    "position": m.get("position"),
                },
            )
            for m in rows
        ]

    def _raw_models(self, scene_id: str) -> list[dict]:
        import httpx

        r = httpx.post(f"{self._base_url}/v1/scene/model/list/", json={"scene_id": str(scene_id)}, timeout=30.0)
        if r.status_code != 200:
            raise errors.ServiceError(errors.PREFORM_API_ERROR, r.text, api_code=str(r.status_code))
        return r.json().get("models", [])

    def auto_support(self, scene_id, params, model_ids=None) -> None:
        extra = {"model_ids": list(model_ids)} if model_ids else {}
        self._long(self._p.auto_support_models, scene_id=scene_id, **extra, **params)

    def regenerate_supports(self, scene_id, model_ids) -> None:
        self._long(self._p.regenerate_supports, scene_id=scene_id, model_ids=model_ids)

    def auto_layout(self, scene_id, *, lock_rotation, seed, model_spacing_mm) -> LayoutResult:
        try:
            self._long(
                self._p.auto_layout_models,
                scene_id=scene_id,
                lock_rotation=lock_rotation,
                seed=seed,
                model_spacing_mm=model_spacing_mm,
                on_layout_failure=OnLayoutFailure.FAIL_AND_LEAVE_SCENE_UNCHANGED,  # OD-03 resolved from SDK enum
            )
        except errors.ServiceError as exc:
            if not exc.api_code:
                raise
            # With FAIL_AND_LEAVE_SCENE_UNCHANGED the scene is untouched; which models did not
            # fit is not reported by the API (UNVERIFIED), so the service reports the API message.
            return LayoutResult(ok=False, unplaced_model_ids=[])
        return LayoutResult(ok=True, unplaced_model_ids=[])

    def run_check(self, scene_id: str, check: str) -> CheckResult:
        fn = {
            "in_bounds": lambda: self._call(self._p.validate_in_bounds, scene_id=scene_id),
            "interferences": lambda: self._call(self._p.validate_interferences, scene_id=scene_id),
            "manifoldness": lambda: self._long(self._p.validate_manifoldness, scene_id=scene_id),
            "thin_features": lambda: self._long(
                self._p.validate_thin_features, scene_id=scene_id, threshold_mm=THIN_FEATURE_THRESHOLD_MM
            ),
            "minima": lambda: self._long(self._p.validate_minima, scene_id=scene_id),
            "supportedness": lambda: self._long(self._p.validate_supportedness, scene_id=scene_id),
            "cups": lambda: self._long(self._p.validate_cups, scene_id=scene_id),
        }[check]
        raw = _plain(fn())
        flagged: dict[str, Any] = {}
        if check == "in_bounds":
            ok = bool(raw.get("all_in_bounds"))
            return CheckResult(check, ok, {} if ok else {"*": raw}, raw)
        if check == "interferences":
            pairs = raw.get("model_ids", [])
            return CheckResult(check, not pairs, {"pairs": pairs} if pairs else {}, raw)
        if check == "manifoldness":
            for mid, r in (raw.get("per_model_results") or {}).items():
                if r.get("is_manifold") is False:
                    flagged[mid] = r
            return CheckResult(check, not flagged, flagged, raw)
        for mid, r in (raw.get("per_model_results") or {}).items():  # UNVERIFIED shapes
            if _walk_flags(r):
                flagged[mid] = r
        return CheckResult(check, not flagged, flagged, raw)

    def list_devices(self) -> list[Device]:
        res = self._call(self._p.list_devices)
        return [
            Device(
                serial=str(getattr(d, "id", "")),
                machine_type=str(getattr(d, "product_name", "")),
                ready_to_print_now=getattr(d, "ready_to_print_now", None),
            )
            for d in res.devices
            if getattr(d, "is_connected", True)
        ]

    def print_scene(self, scene_id, printer, job_name) -> str | None:
        res = self._long(
            self._p.print_scene,
            scene_id=scene_id,
            printer=printer,
            job_name=job_name,
            print_now=False,  # ALWAYS explicit (spec rule 9, A1)
        )
        return str(res.job_id) if getattr(res, "job_id", None) else None
