"""Smoke tests of the window against a fake backend. Skipped where Tk has no display."""

import sys
import time
import tkinter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402
import core  # noqa: E402


class FakeBackend:
    def server_reachable(self):
        return True

    def owns_server(self):
        return False

    def start_server(self):
        pass

    def stop_server(self):
        pass

    def print_form(self, *args, **kwargs):
        return "ok"

    def list_printers(self, start_server=True):
        return [
            {"id": "A", "status": "Ready", "ready_to_print_now": True, "connection_type": "WIFI"},
            {"id": "B", "status": "Printing", "ready_to_print_now": False, "connection_type": "REMOTE"},
        ]


@pytest.fixture
def window(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app, "find_server_exe", lambda configured="": "")
    monkeypatch.setattr(app, "PreFormBackend", lambda **kwargs: FakeBackend())  # never touch the real SDK or server
    try:
        with capfd.disabled():  # Tk's startup fails at random while pytest has stdout/stderr captured
            w = app.App()
    except tkinter.TclError as exc:
        if "display" in str(exc):
            pytest.skip(f"no display: {exc}")
        raise
    pump(w, 5)
    yield w
    w.destroy()


def pump(w, n=30):
    for _ in range(n):
        w.update()
        w._drain_ui_queue()
        time.sleep(0.01)


def make_form(tmp_path):
    form = tmp_path / "part.form"
    form.write_bytes(b"x")
    return form


def test_printer_panel_shows_name_and_status(window):
    window.refresh_printers()
    pump(window)
    rows = [window.printer_tree.item(i, "values") for i in window.printer_tree.get_children()]
    assert rows[0][0] == "A" and "Ready to print" in rows[0][1]
    assert rows[1][0] == "B" and "Printing" in rows[1][1]


def test_selecting_a_row_picks_the_printer_and_schedule_needs_everything(window, tmp_path):
    window.refresh_printers()
    pump(window)
    assert str(window.schedule_btn["state"]) == "disabled"
    window.form_var.set(str(make_form(tmp_path)))
    window.printer_tree.selection_set("A")
    pump(window, 5)
    assert window._printer_id() == "A"
    window._apply_time(datetime.now() + timedelta(hours=2))
    pump(window, 5)
    assert str(window.schedule_btn["state"]) == "normal"
    window._apply_time(datetime.now() - timedelta(hours=2))
    pump(window, 5)
    assert str(window.schedule_btn["state"]) == "disabled" and "past" in window.summary["text"]


def test_jobs_listed_with_countdown(window, tmp_path):
    job = core.new_job(str(make_form(tmp_path)), "A", datetime.now() + timedelta(hours=3))
    window.scheduler.add(job)
    pump(window)
    values = window.tree.item(job.id, "values")
    assert "Scheduled" in values[3] and values[4].startswith("Starts in")


def test_waiting_job_shows_and_can_be_cancelled(window, tmp_path):
    job = core.Job("w1", str(make_form(tmp_path)), "A", (datetime.now() - timedelta(minutes=2)).isoformat(), core.WAITING, "Printer not ready.")
    window.scheduler.jobs = [job]
    window.refresh()
    window.tree.selection_set("w1")
    pump(window, 5)
    assert "Waiting for printer" in window.tree.item("w1", "values")[3]
    assert str(window.cancel_btn["state"]) == "normal"


def test_attention_message_counts_jobs_that_did_not_start(window, tmp_path):
    form, old = make_form(tmp_path), (datetime.now() - timedelta(hours=1)).isoformat()
    window.scheduler.jobs = [
        core.Job("a", str(form), "A", old, core.FAILED, "x"),
        core.Job("b", str(form), "A", old, core.QUEUED, "x"),
        core.Job("c", str(form), "A", old, core.DONE, "x"),
    ]
    window.refresh()
    assert "2 print(s)" in window.attention["text"]


def test_wait_minutes_setting_is_saved_and_clamped(window):
    window.wait_var.set(45)
    assert window._wait_minutes == 45 and window.settings.get("wait_minutes") == "45"
    window.wait_var.set(5000)
    assert window._wait_minutes == 720
    assert window.scheduler.wait_window() == timedelta(minutes=720)


def test_a_failing_tick_does_not_stop_the_timer(window, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(window.scheduler, "tick", boom)
    window._tick()  # must not raise
    assert "kaboom" in window.status["text"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_second_copy_is_detected():
    import subprocess
    import uuid

    name = f"Local\\test-{uuid.uuid4().hex}"
    assert app.another_copy_is_running(name) is False
    code = f"import sys; sys.path.insert(0, r'{Path(app.__file__).parent}'); import app; print(app.another_copy_is_running({name!r}))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()
    assert out == "True"
