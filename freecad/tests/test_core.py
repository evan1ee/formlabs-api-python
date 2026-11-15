from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import pytest

from formlabs_fc import constants as C
from formlabs_fc import orientation
from formlabs_fc.client import ServiceClient, ServiceError
from formlabs_fc.exporter import ExportedBody
from formlabs_fc.send import BackgroundSend, Sender
from formlabs_fc.settings import Settings


def close(a, b):
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b))


# --- orientation ----------------------------------------------------------------------------------------------
S = math.sqrt(0.5)
FRONT = orientation.quaternion_to_matrix(S, 0, 0, S)  # FreeCAD Front view


def test_front_view_is_identity():
    r = orientation.rotation_for("view", FRONT)
    assert close(orientation.apply(r, (1, 2, 3)), (1, 2, 3))


def test_top_view_lays_the_part_flat_as_seen():
    top = orientation.quaternion_to_matrix(0, 0, 0, 1)  # looking down -Z: screen up = +Y, toward viewer = +Z
    r = orientation.rotation_for("view", top)
    # world +Z (toward the viewer) is screen c=+1 -> PreForm (0, -1, 0); world +Y is screen up -> PreForm +Z
    assert close(orientation.apply(r, (0, 0, 1)), (0, -1, 0))
    assert close(orientation.apply(r, (0, 1, 0)), (0, 0, 1))


def test_modes_without_a_view():
    assert orientation.rotation_for("view", None) == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert close(orientation.apply(orientation.rotation_for("yup", None), (0, 1, 0)), (0, 0, 1))


def test_rotation_is_orthonormal():
    r = orientation.rotation_for("view", orientation.quaternion_to_matrix(0.3, 0.5, 0.1, 0.8))
    assert math.isclose(abs(sum(r[0][i] * r[1][i] for i in range(3))), 0, abs_tol=1e-9)
    assert math.isclose(sum(v * v for v in r[0]), 1, abs_tol=1e-9)


# --- settings -------------------------------------------------------------------------------------------------
@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("FL_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.delenv("FL_INSTALL_DIR", raising=False)
    return Settings(tmp_path / "s.json")


def test_defaults(settings):
    assert settings.material == "FLTO2002" and C.material_name(settings.material) == "Tough 2000 V2"
    assert settings.layer == "0.1" and settings.printer == "Form 4B"
    assert settings.orientation == "view" and settings.export_format == "STEP"


def test_only_five_materials_and_invalid_is_ignored(settings):
    assert [m.name for m in C.MATERIALS] == ["Tough 2000 V2", "Grey V5", "White V5", "Clear V5", "Rigid 10K"]
    settings.material = "NOPE"
    assert settings.material == "FLTO2002"
    settings.material = "FLGPGR05"
    assert settings.material == "FLGPGR05"


def test_project_folder_is_one_per_day_and_rolls_over(settings):
    d1 = datetime(2026, 11, 14, 9, 0)
    d2 = datetime(2026, 11, 15, 9, 0)
    assert settings.project_dir(d1).name == "2026-11-14"
    assert settings.project_dir(d1).name == "2026-11-14"  # stable within the day
    assert settings.project_dir(d2).name == "2026-11-15"  # next day rolls over
    settings.project_dir(d2).mkdir(parents=True)
    assert settings.new_project_folder(d2).name == "2026-11-15-2"
    settings.set_project_dir(settings.new_project_folder(d2))
    assert settings.project_dir(d2).name == "2026-11-15-2"  # a second project the same day is kept


# --- send flow against the real service -----------------------------------------------------------------------
def _body(tmp_path: Path, name="partA", content=b"solid-a") -> ExportedBody:
    f = tmp_path / "staging" / f"{name}.step"
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(content)
    return ExportedBody(name, name, f, orientation.to_4x4(orientation.rotation_for("same", None)), "C:/cad/x.FCStd")


def make_sender(settings, live_service):
    port, _svc, _p = live_service
    settings.material = "FLGPGR05"
    sender = Sender(settings, host=None, connect=lambda: ServiceClient(port, "test-token"))
    return sender


def test_send_generates_supports_and_layout(settings, live_service, tmp_path):
    _, svc, fake = live_service
    res = make_sender(settings, live_service).send([_body(tmp_path)])
    assert res.sent == 1 and "Supports generated and parts laid out" in res.text
    names = [c[0] for c in fake.calls]
    assert "import_model" in names and "auto_support" in names and "auto_layout" in names
    assert fake.support_params["internal_supports_enabled"] is False


def test_resend_unchanged_does_nothing_and_changed_replaces(settings, live_service, tmp_path):
    sender = make_sender(settings, live_service)
    sender.send([_body(tmp_path, content=b"v1")])
    again = sender.send([_body(tmp_path, content=b"v1")])
    assert again.note == ""  # unchanged: no new supports or layout
    changed = sender.send([_body(tmp_path, content=b"v2")])
    assert "Supports generated" in changed.note


def test_batch_of_parts_lands_in_one_build(settings, live_service, tmp_path):
    _, svc, _ = live_service
    make_sender(settings, live_service).send([_body(tmp_path, "a", b"1"), _body(tmp_path, "b", b"2")])
    assert len(svc.store.builds()) == 1


def test_unsupported_material_is_a_readable_error(settings, live_service, tmp_path):
    sender = make_sender(settings, live_service)
    settings.material = "FLTO2002"  # not valid on the fake printer
    with pytest.raises(ServiceError):
        sender.send([_body(tmp_path)])


def test_background_send_reports_failure_in_status(settings, tmp_path):
    def boom():
        raise ServiceError("PREFORM_NOT_RUNNING", "x")

    bg = BackgroundSend(Sender(settings, host=None, connect=boom))
    bg.start([_body(tmp_path)])
    bg._thread.join(5)
    assert bg.poll().startswith("Send failed: PreForm is not running")
    assert bg.poll() is None


def test_concurrent_settings_writes_never_lose_values(settings):
    """A torn read used to reset other keys to defaults (a send silently switched material)."""
    import threading

    settings.material = "FLGPGR05"
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            settings.set_project_dir(settings.projects_root / f"2026-11-15-{i % 5 + 2}")
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(300):
            settings.layer = "0.05"
            assert settings.material == "FLGPGR05" and settings.layer == "0.05"
    finally:
        stop.set()
        t.join()


def test_unreachable_preform_gives_a_readable_message():
    from formlabs_fc.send import friendly

    e = ServiceError("SERVICE_START_FAILED", "cannot connect on 44388: SERVER_UNREACHABLE: no PreFormServer reachable at http://localhost:44388")
    assert friendly(e).startswith("PreForm is not running")
