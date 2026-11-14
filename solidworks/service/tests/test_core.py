from __future__ import annotations

import pytest
from attrs import evolve

from formlabs_sw_service import errors
from formlabs_sw_service.core import ProjectService
from formlabs_sw_service.errors import ServiceError
from formlabs_sw_service.models import (
    BuildStatus,
    JobStatus,
    Lock,
    ModelStatus,
    OpState,
    ValidationStatus,
)
from formlabs_sw_service.ports import CheckResult


def test_version_pin_refused(tmp_path, port):
    port.version = "3.64.2.665"
    with pytest.raises(ServiceError) as e:
        ProjectService(tmp_path / "p", port).connect()
    assert e.value.app_code == errors.PREFORM_SERVER_VERSION_UNSUPPORTED  # AT-20
    assert "3.66.0.1146" in e.value.message and "3.64.2.665" in e.value.message


def test_import_uses_default_lock_and_explicit_units(svc, port, make_req):
    r = svc.send_model(make_req())
    assert r["action"] == "imported"
    _, kw = next(c for c in port.calls if c[0] == "import_model")
    assert kw["lock"] == Lock.ROTATION_LOCKED.value and kw["units"] == "MILLIMETERS"
    assert not any(c[0] in ("orient_models", "auto_orient") for c in port.calls)


def test_resend_unchanged_is_noop(svc, make_req):  # AT-16
    a = svc.send_model(make_req())
    b = svc.send_model(make_req())
    assert b["action"] == "unchanged" and b["model_id"] == a["model_id"]
    assert len(svc.store.models_of(a["build_id"])) == 1


def test_default_supports_exclude_internal(svc, port, make_req):
    a = svc.send_model(make_req())
    svc.generate_supports(a["build_id"])
    assert port.support_params["internal_supports_enabled"] is False
    svc.generate_supports(a["build_id"], {"internal_supports_enabled": True})
    assert port.support_params["internal_supports_enabled"] is True


def test_resend_changed_replaces_and_keeps_lock(svc, port, make_req):  # AT-17
    a = svc.send_model(make_req(lock_mode=Lock.XY_ROTATION_FREE))
    svc.generate_supports(a["build_id"])
    svc.validate(a["build_id"])
    b = svc.send_model(make_req(content=b"solid-b", lock_mode=Lock.XY_ROTATION_FREE))
    assert b["action"] == "replaced" and b["model_id"] == a["model_id"]
    imports = [kw for n, kw in port.calls if n == "import_model"]
    assert imports[-1]["lock"] == Lock.XY_ROTATION_FREE.value
    m = svc.store.get_model(a["model_id"])
    assert m.status == ModelStatus.SUPPORTS_STALE
    assert svc.store.get_build(a["build_id"]).validation_status == ValidationStatus.NOT_RUN


def test_different_config_moves_between_builds(svc, make_req):
    a = svc.send_model(make_req())
    b = svc.send_model(make_req(material="FLGPCL05"))
    assert b["action"] == "moved" and b["to_build_id"] != a["build_id"]
    assert svc.store.models_of(a["build_id"]) == []
    assert svc.store.get_build(a["build_id"]).status == BuildStatus.EMPTY


def test_grouping_by_key_and_layer_normalisation(svc, make_req):
    a = svc.send_model(make_req(body="b1", layer=0.1))
    b = svc.send_model(make_req(body="b2", layer=0.1000004))
    c = svc.send_model(make_req(body="b3", layer=0.05))
    assert a["build_id"] == b["build_id"] != c["build_id"]


def test_multi_body_one_model_per_body(svc, make_req):  # AT-21
    ids = {svc.send_model(make_req(body=f"b{i}"))["model_id"] for i in range(3)}
    assert len(ids) == 3


def test_unknown_material_blocks_send(svc, make_req):
    with pytest.raises(ServiceError) as e:
        svc.send_model(make_req(material="NOPE"))
    assert e.value.app_code == errors.MATERIAL_NOT_SUPPORTED


def test_export_path_must_be_inside_exports(svc, make_req, tmp_path):
    req = make_req()
    outside = tmp_path / "evil.step"
    outside.write_bytes(b"x")
    with pytest.raises(ServiceError) as e:
        svc.send_model(evolve(req, export_file=str(outside)))
    assert e.value.app_code == errors.PATH_OUTSIDE_PROJECT


def test_fully_locked_not_selectable(svc, make_req):
    with pytest.raises(ServiceError):
        svc.send_model(make_req(lock_mode=Lock.FULLY_LOCKED))


def test_layout_failure_reported_and_scene_restored(svc, port, make_req):  # AT-18
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])
    port.fail_layout = True
    with pytest.raises(ServiceError) as e:
        svc.layout(a["build_id"])
    assert e.value.app_code == errors.LAYOUT_WOULD_EJECT
    lay = next(kw for n, kw in port.calls if n == "auto_layout")
    assert lay["lock_rotation"] is True and lay["seed"] == 1
    sid = svc._scene[a["build_id"]]  # noqa: SLF001
    assert len(port.scenes[sid]) == 1  # scene reloaded from the saved .form


def test_validation_gating_and_ack(svc, port, make_req):
    a = svc.send_model(make_req())
    bid = a["build_id"]
    port.checks["cups"] = CheckResult("cups", False, {"pm": 1}, {})
    res = svc.validate(bid)
    assert res["warnings"] and not res["blocking"]
    with pytest.raises(ServiceError):  # not yet acknowledged
        svc.submit_build(bid, "Form4-A", "j", confirmed=True)
    svc.acknowledge_warnings(bid, res["run_id"])
    assert svc.store.get_build(bid).validation_status == ValidationStatus.WARNINGS_ACKED
    svc.send_model(make_req(content=b"changed"))  # scene change clears acknowledgement
    assert svc.store.get_build(bid).validation_status == ValidationStatus.NOT_RUN
    with pytest.raises(ServiceError):
        svc.acknowledge_warnings(bid, res["run_id"])


def test_blocking_check_cannot_be_acked(svc, port, make_req):
    a = svc.send_model(make_req())
    port.checks["in_bounds"] = CheckResult("in_bounds", False, {"*": 1}, {})
    res = svc.validate(a["build_id"])
    assert res["status"] == "BLOCKED"
    with pytest.raises(ServiceError) as e:
        svc.acknowledge_warnings(a["build_id"], res["run_id"])
    assert e.value.app_code == errors.VALIDATION_BLOCKED


def _ready(svc, make_req):
    a = svc.send_model(make_req())
    svc.validate(a["build_id"])
    return a["build_id"]


def test_submit_queues_with_print_now_false(svc, port, make_req):  # AT-19
    bid = _ready(svc, make_req)
    job = svc.submit_build(bid, "Form4-A", "job", confirmed=True)
    assert job.status == JobStatus.SUCCEEDED and job.print_now is False
    assert ("print_scene", {"printer": "Form4-A", "print_now": False}) in port.calls
    assert svc.store.get_build(bid).status == BuildStatus.SUBMITTED


def test_submit_requires_confirmation_and_matching_printer(svc, port, make_req):
    bid = _ready(svc, make_req)
    with pytest.raises(ServiceError):
        svc.submit_build(bid, "Form4-A", "j", confirmed=False)
    port.devices = [type(port.devices[0])("Form3-A", "Form 3", True)]
    with pytest.raises(ServiceError) as e:
        svc.submit_build(bid, "Form3-A", "j", confirmed=True)
    assert e.value.app_code == errors.PRINTER_MISMATCH


def test_print_timeout_marks_unknown_never_retries(svc, port, make_req):
    bid = _ready(svc, make_req)
    port.print_error = TimeoutError("boom")
    with pytest.raises(ServiceError) as e:
        svc.submit_build(bid, "Form4-A", "j", confirmed=True)
    assert e.value.app_code == errors.OPERATION_STATE_UNCERTAIN
    assert svc.store.jobs_of(bid)[0].status == JobStatus.UNKNOWN
    assert sum(1 for n, _ in port.calls if n == "print_scene") == 1


def test_journal_written_before_mutation_and_uncertain_on_timeout(svc, port, make_req):
    port.import_error = TimeoutError("t")
    with pytest.raises(TimeoutError):
        svc.send_model(make_req())
    ops = svc.journal.all_ops()
    assert ops[0].kind == "import" and ops[0].state == OpState.UNCERTAIN


def test_restore_after_server_restart_remaps_by_name(tmp_path, port, make_req, svc):
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])
    mid = a["model_id"]
    port.restart()
    svc2 = ProjectService(svc.folder, port, autosave=False)
    assert svc2.connect()["mismatches"] == []
    assert svc2._scene == {}  # an earlier session's build is not reopened until it is used  # noqa: SLF001
    assert svc2._open_and_remap(svc2.store.get_build(a["build_id"])) == []  # noqa: SLF001
    assert svc2._pmodel[mid] in port.scenes[svc2._scene[a["build_id"]]]  # noqa: SLF001


def test_restore_reports_missing_model(tmp_path, port, make_req, svc):
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])
    for form in list(port.forms.values()):
        form.clear()
    port.restart()
    svc2 = ProjectService(svc.folder, port)
    svc2.connect()
    report = svc2._open_and_remap(svc2.store.get_build(a["build_id"]))  # noqa: SLF001
    assert report and report[0]["problem"] == "MISSING_IN_SCENE"


def test_recover_print_is_flagged_not_retried(svc, port, make_req):
    bid = _ready(svc, make_req)
    svc.journal.begin("print", bid, None, {"job_id": "x"})
    out = svc.recover()
    assert out[0]["outcome"] == "UNKNOWN_CHECK_PRINTER_QUEUE"
    assert not any(n == "print_scene" for n, _ in port.calls)


def test_atomic_save_keeps_bak(svc, make_req):
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])
    svc.save_build(a["build_id"])
    form = svc.folder / svc.store.get_build(a["build_id"]).form_file
    assert form.exists() and form.with_suffix(".form.bak").exists()


def test_autosave_is_debounced(tmp_path, port, make_req, svc):
    import time

    s = ProjectService(tmp_path / "deb", port, autosave=True, autosave_delay_s=0.2)
    s.connect()
    f = lambda body: type(make_req())  # noqa: E731 - keep make_req bound to svc folder
    r1 = make_req(body="a")
    exports = s.folder / "exports"
    (exports / "a.step").write_bytes(b"a")
    (exports / "b.step").write_bytes(b"b")
    from attrs import evolve

    s.send_model(evolve(r1, export_file=str(exports / "a.step")))
    s.send_model(evolve(r1, body_id="b", export_file=str(exports / "b.step")))
    assert sum(1 for p in port.forms if p.endswith(".tmp.form")) == 0  # nothing saved yet
    time.sleep(0.6)
    assert sum(1 for p in port.forms if p.endswith(".tmp.form")) == 1  # one save for the burst
    s.cancel_autosave()


def test_recover_import_found_in_scene_creates_record(svc, port, make_req):
    from formlabs_sw_service.core import _req_doc

    req = make_req()
    b = svc._find_or_create_build(req)  # noqa: SLF001
    scene = svc._ensure_scene(b)  # noqa: SLF001
    port.scenes[scene]["pm-x"] = {"name": "m1", "lock": "L", "hash": "h", "supports": False}
    svc.journal.begin("import", b.build_id, "m1", {"file": req.export_file, "lock": "L", "request": _req_doc(req), "file_hash": "h"})
    assert svc.recover()[0]["outcome"] == "FOUND_IN_SCENE"
    assert svc.store.get_model("m1") is not None


def test_recover_import_missing_retries_once(svc, port, make_req):
    from formlabs_sw_service.core import _req_doc

    req = make_req()
    b = svc._find_or_create_build(req)  # noqa: SLF001
    svc._ensure_scene(b)  # noqa: SLF001
    svc.journal.begin("import", b.build_id, "m2", {"file": req.export_file, "lock": "L", "request": _req_doc(req), "file_hash": "h"})
    assert svc.recover()[0]["outcome"] == "RETRIED_OK"
    assert sum(1 for n, _ in port.calls if n == "import_model") == 1
    assert svc.store.get_model("m2") is not None


def test_replace_of_unsupported_model_stays_imported(svc, make_req):
    a = svc.send_model(make_req())
    svc.send_model(make_req(content=b"changed"))
    assert svc.store.get_model(a["model_id"]).status == ModelStatus.IMPORTED


def test_build_and_project_naming(tmp_path, port):
    from datetime import datetime

    fixed = datetime(2026, 11, 14, 15, 30, 12)
    s = ProjectService(tmp_path / "p", port, autosave=False, clock=lambda: fixed)
    s.connect()
    assert s.project.name == "2026-11-14"
    f = s.folder / "exports" / "a.step"
    f.write_bytes(b"a")
    from formlabs_sw_service.core import SendRequest

    def req(material, body):
        return SendRequest("C:/d.sldprt", "Default", body, body, str(f), "STEP", "FORM-4-0", material, 0.1)

    a = s.send_model(req("FLGPGR05", "b1"))
    b = s.send_model(req("FLGPCL05", "b2"))
    names = {x.name for x in s.store.builds()}
    assert names == {"2026-11-14-15-30-12-Grey-V5", "2026-11-14-15-30-12-Clear-V5"}
    assert s.store.get_build(a["build_id"]).form_file == "builds/2026-11-14-15-30-12-Grey-V5.form"


def test_build_name_collision_gets_suffix():
    from datetime import datetime
    from formlabs_sw_service.naming import build_name

    t = datetime(2026, 1, 2, 3, 4, 5)
    first = build_name(t, "FLGPGR05")
    assert build_name(t, "FLGPGR05", {first}) == first + "-2"
    assert build_name(t, "FLGPGR05", {first, first + "-2"}) == first + "-3"


def test_new_project_folder_is_dated_and_unique(tmp_path):
    from datetime import datetime
    from formlabs_sw_service.naming import new_project_folder

    t = datetime(2026, 1, 2, 3, 4, 5)
    p1 = new_project_folder(tmp_path, t)
    p1.mkdir()
    assert p1.name == "2026-01-02" and new_project_folder(tmp_path, t).name == "2026-01-02-2"


def test_save_project_saves_dirty_builds_and_writes_manifest(svc, make_req):
    import json

    a = svc.send_model(make_req())
    assert svc.store.get_build(a["build_id"]).dirty
    res = svc.save_project()
    b = svc.store.get_build(a["build_id"])
    assert not b.dirty and res["saved_builds"] == [b.name]
    m = json.loads((svc.folder / "project.json").read_text(encoding="utf-8"))
    assert m["builds"][0]["name"] == b.name and m["builds"][0]["models"] == ["body1"]
    assert (svc.folder / b.form_file).exists()


def test_project_reuses_datetime_folder_name(tmp_path, port):
    s = ProjectService(tmp_path / "2026-01-02-03-04-05", port, autosave=False)
    assert s.project.name == "2026-01-02-03-04-05"


def test_form4b_printer_accepted_via_catalog(svc, port, make_req):
    port.list_print_settings = lambda: {  # Form 4 and Form 4B share FORM-4-0
        "printer_types": [{"supported_product_names": ["Form 4B"], "supported_machine_type_ids": ["FORM-4-0"]}]
    }
    port.devices = [type(port.devices[0])("Form4B-X", "Form 4B", True)]
    bid = _ready(svc, make_req)
    assert svc.submit_build(bid, "Form4B-X", "j", confirmed=True).status == JobStatus.SUCCEEDED


def test_print_setting_resolved_from_catalog(svc, port, make_req):
    ms = lambda label, ps: {"label": label, "scene_settings": {"machine_type": "FORM-4-0", "material_code": "FLGPGR05", "print_setting": ps, "layer_thickness_mm": 0.1}}  # noqa: E731
    port.list_print_settings = lambda: {"printer_types": [{"materials": [{"material_settings": [
        ms("0.100 mm (Supports V2 settings)", "SUPPORTSV2"), ms("0.100 mm (Default settings)", "SUPPORTSV1")]}]}]}
    r = svc.send_model(make_req())
    assert svc.store.get_build(r["build_id"]).print_setting == "SUPPORTSV1"


def test_send_after_preform_restart_reopens_or_reimports(svc, port, make_req):
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])  # saved: the .form lets the scene come back
    port.scenes.clear()  # PreForm was closed and reopened
    again = svc.send_model(make_req(body="body2", content=b"solid-2"))
    assert again["action"] == "imported"
    svc.generate_supports(again["build_id"])  # works against the reopened scene


def test_unsaved_build_is_reimported_after_preform_restart(svc, port, make_req):
    svc.cancel_autosave()
    a = svc.send_model(make_req())
    svc.cancel_autosave()
    form = svc.folder / svc.store.get_build(a["build_id"]).form_file
    form.unlink(missing_ok=True)
    port.scenes.clear()
    b = svc.send_model(make_req())  # same unchanged body: must not be a no-op
    assert b["action"] == "imported"


def test_new_session_starts_a_new_build_instead_of_reusing_the_old_one(tmp_path, port, make_req, svc):
    a = svc.send_model(make_req())
    svc.save_build(a["build_id"])
    port.restart()  # PreForm and SOLIDWORKS were closed and reopened
    svc2 = ProjectService(svc.folder, port, autosave=False)
    svc2.connect()
    b = svc2.send_model(make_req(body="body2", content=b"solid-2"))
    assert b["build_id"] != a["build_id"]
    c = svc2.send_model(make_req(body="body3", content=b"solid-3"))
    assert c["build_id"] == b["build_id"]  # within the session parts still share a build
    assert len({x.name for x in svc2.store.builds()}) == 2


def test_send_after_deleting_the_model_in_preform_imports_again(svc, port, make_req):
    a = svc.send_model(make_req())
    for models in port.scenes.values():
        models.clear()  # the user deleted the part in PreForm
    b = svc.send_model(make_req())  # same unchanged body
    assert b["action"] == "imported" and b["build_id"] == a["build_id"]


def test_send_after_deleting_one_build_in_preform_starts_a_new_build(svc, port, make_req):
    a = svc.send_model(make_req(body="b1", material="FLGPGR05"))
    c = svc.send_model(make_req(body="b2", material="FLGPCL05", content=b"solid-c"))
    port.scenes.pop(svc._scene[a["build_id"]])  # noqa: SLF001 - the user deleted the Grey build
    again = svc.send_model(make_req(body="b1", material="FLGPGR05"))
    assert again["action"] == "imported" and again["build_id"] not in (a["build_id"], c["build_id"])

