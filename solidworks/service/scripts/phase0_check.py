"""Phase 0 check (spec §15): run on a machine with PreForm Server 3.64.2.3797. Prints PASS/FAIL per step.

Usage:  python scripts/phase0_check.py <PreFormServer.exe | connect> <part.step-or.stl> [printer-serial]
"connect" attaches to a server already listening on 44388 (e.g. PreForm > File > Start PreForm Server).
Resolves OD-01 (position kept?), OD-02 (lock strings), OD-04/05/06 by recording what the server does.
A printer, if given, only ever receives print_now=False.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from formlabs_sw_service import PINNED_SERVER_VERSION
from formlabs_sw_service.models import Lock
from formlabs_sw_service.sdk_adapter import SdkAdapter

CHECKS = ("in_bounds", "interferences", "manifoldness", "thin_features", "minima", "supportedness", "cups")


def step(name: str, fn):
    try:
        out = fn()
        print(f"PASS {name}: {out if out is not None else ''}")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name}: {exc!r}")
        return None


def main() -> int:
    exe, part = sys.argv[1], str(Path(sys.argv[2]).resolve())
    printer = sys.argv[3] if len(sys.argv) > 3 else None
    adapter, close = SdkAdapter.connect() if exe == "connect" else SdkAdapter.launch(exe)
    try:
        v = step("server version", adapter.server_version)
        print("PINNED" if v == PINNED_SERVER_VERSION else f"MISMATCH (expected {PINNED_SERVER_VERSION})")
        scene = step("create scene", lambda: adapter.create_scene("FORM-4-0", "FLGPGR05", 0.1, "DEFAULT"))
        for lock in Lock:  # OD-02: which lock strings does the server accept?
            step(f"import with lock {lock.value}", lambda lock=lock: adapter.import_model(
                scene, part, name=f"t-{lock.name}", lock=lock.value, units="MILLIMETERS",
                chordal_tolerance_um=10.0, angle_tolerance_deg=5.0))
        step("OD-01 positions after import", lambda: [(m.name, m.fingerprint.get("bbox")) for m in adapter.list_models(scene)])
        step("layout (non-ejecting)", lambda: adapter.auto_layout(scene, lock_rotation=True, seed=1, model_spacing_mm=2.0))
        for c in CHECKS:
            step(f"validate {c}", lambda c=c: adapter.run_check(scene, c).passed)
        out = Path(tempfile.mkdtemp()) / "phase0.form"
        step("save form", lambda: adapter.save_form_file(scene, str(out)))
        step("reopen form", lambda: len(adapter.list_models(adapter.open_form_file(str(out)))))
        if printer:
            step("queue print_now=False", lambda: adapter.print_scene(scene, printer, "phase0"))
    finally:
        close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
