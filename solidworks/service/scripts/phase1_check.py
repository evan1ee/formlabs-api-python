"""Phase 1 check against a live PreForm server (connect mode). No printer is touched.

Usage: python scripts/phase1_check.py <step_v1> <step_v2> <project_dir>
step_v2 must differ from step_v1 (same body, edited) to exercise replace-in-place.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from formlabs_sw_service.core import ProjectService, SendRequest
from formlabs_sw_service.models import ModelStatus
from formlabs_sw_service.sdk_adapter import SdkAdapter


def step(name, fn):
    try:
        out = fn()
        print(f"PASS {name}: {out if out is not None else ''}")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name}: {exc!r}")
        return None


def main() -> int:
    v1, v2, proj = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    adapter, close = SdkAdapter.connect()
    try:
        svc = ProjectService(proj, adapter, autosave=False)
        print("connect:", svc.connect())
        ex = svc.folder / "exports"
        shutil.copy(v1, ex / "part_v1.step")
        shutil.copy(v2, ex / "part_v2.step")

        def req(name, mat="FLGPGR05"):
            return SendRequest(
                document="C:/cad/part.sldprt", configuration="Default", body_id="BODY1", body_name="Boss-Extrude1",
                export_file=str(ex / name), export_format="STEP", machine_type="FORM-4-0",
                material_code=mat, layer_thickness_mm=0.1,
            )

        a = step("send new (STEP, locked)", lambda: svc.send_model(req("part_v1.step")))
        bid, mid = a["build_id"], a["model_id"]
        step("scene model bbox (OD-01)", lambda: [(m.name, m.lock, m.fingerprint["bbox"]) for m in adapter.list_models(svc._scene[bid])])
        step("re-send unchanged -> no-op", lambda: svc.send_model(req("part_v1.step"))["action"])
        step("re-send changed -> replace", lambda: svc.send_model(req("part_v2.step"))["action"])
        step("lock kept after replace", lambda: [m.lock for m in adapter.list_models(svc._scene[bid])])
        step("model stale supports", lambda: svc.store.get_model(mid).status == ModelStatus.SUPPORTS_STALE)
        step("supports", lambda: svc.generate_supports(bid).status.value)
        step("layout", lambda: svc.layout(bid).status.value)
        step("validate", lambda: {k: v for k, v in svc.validate(bid).items() if k != "run_id"})
        step("save", lambda: svc.save_build(bid).dirty)
        step("build name / project name", lambda: (svc.store.get_build(bid).name, svc.project.name))
        step("save project", lambda: svc.save_project())
        step("printers (no submit)", lambda: svc.list_printers())

        # Restore: a fresh service object on the same folder re-opens the .form and re-maps by name.
        svc2 = ProjectService(proj, adapter, autosave=False)
        rep = step("restore + remap", lambda: svc2.connect())
        step("remapped model present", lambda: mid in svc2._pmodel)
        return 0 if rep is not None else 1
    finally:
        close()


if __name__ == "__main__":
    raise SystemExit(main())
