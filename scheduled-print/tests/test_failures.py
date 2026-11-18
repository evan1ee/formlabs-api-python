"""Every way a scheduled print can go wrong, and what the job list must say about it."""

import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402


class ApiError(Exception):
    """Stands in for formlabs_sdk's PreFormApiError."""

    def __init__(self, code, message="boom"):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class Backend:
    """Scripted: ready_script gives printer_ready() answers in order (the last one repeats); print_errors are raised in order."""

    def __init__(self, ready_script=(True,), print_errors=()):
        self.ready_script, self.print_errors = list(ready_script), list(print_errors)
        self.print_calls, self.ready_calls = [], 0

    def list_printers(self, start_server=True):
        return []

    def ensure_server(self):
        pass

    def printer_ready(self, printer):
        i = min(self.ready_calls, len(self.ready_script) - 1)
        self.ready_calls += 1
        value = self.ready_script[i]
        if isinstance(value, Exception):
            raise value
        return value

    def print_form(self, form_file, printer, job_name, mode="auto"):
        self.print_calls.append(mode)
        if self.print_errors:
            err = self.print_errors.pop(0)
            if err is not None:
                raise err
        return core.PrintOutcome("sent", started=mode != "queue")


@pytest.fixture
def form(tmp_path):
    f = tmp_path / "part.form"
    f.write_bytes(b"x")
    return f


def scheduler(tmp_path, backend, window_s=5.0):
    return core.Scheduler(core.JobStore(tmp_path / "j.json"), backend, wait_window=lambda: timedelta(seconds=window_s), poll_seconds=0.01)


def due_job(form, status=core.PENDING):
    return core.Job("j1", str(form), "P", (datetime.now() - timedelta(milliseconds=10)).isoformat(), status)


def run(s, job):
    s.add(job)
    s.tick()
    for _ in range(300):
        if s._status(job.id) not in (core.PENDING, core.RUNNING, core.WAITING):
            break
        time.sleep(0.01)
    return s.jobs[0]


def test_starts_as_soon_as_the_printer_becomes_ready(tmp_path, form):
    b = Backend(ready_script=[False, False, True])
    job = run(scheduler(tmp_path, b), due_job(form))
    assert job.status == core.DONE and b.print_calls == ["now"]  # "now": the SDK refuses if it stopped being ready


def test_never_ready_is_queued_only_after_the_window(tmp_path, form):
    b = Backend(ready_script=[False])
    job = run(scheduler(tmp_path, b, window_s=0.1), due_job(form))
    assert job.status == core.QUEUED and b.print_calls == ["queue"]
    assert "not ready" in job.message and b.ready_calls > 1  # it did keep checking first


def test_zero_window_queues_immediately(tmp_path, form):
    b = Backend(ready_script=[False])
    job = run(scheduler(tmp_path, b, window_s=0), due_job(form))
    assert job.status == core.QUEUED and b.ready_calls == 1


def test_server_down_then_back_is_retried(tmp_path, form):
    b = Backend(ready_script=[ApiError("SERVER_UNREACHABLE"), ApiError("STARTUP_FAILED"), True])
    job = run(scheduler(tmp_path, b), due_job(form))
    assert job.status == core.DONE and b.print_calls == ["now"]


def test_server_never_back_fails_and_says_nothing_was_sent(tmp_path, form):
    b = Backend(ready_script=[ApiError("SERVER_UNREACHABLE", "no PreFormServer reachable")])
    job = run(scheduler(tmp_path, b, window_s=0.1), due_job(form))
    assert job.status == core.FAILED and "nothing was sent" in job.message and not b.print_calls


def test_printer_turned_not_ready_between_check_and_send_is_retried(tmp_path, form):
    b = Backend(ready_script=[True], print_errors=[ApiError("OPERATION_FAILED", "printer not ready"), None])
    job = run(scheduler(tmp_path, b), due_job(form))
    assert job.status == core.DONE and b.print_calls == ["now", "now"]


def test_refusal_for_other_reasons_is_not_retried(tmp_path, form):
    b = Backend(ready_script=[None], print_errors=[ApiError("OPERATION_FAILED", "model out of bounds")])  # None: printer not listed -> "auto"
    job = run(scheduler(tmp_path, b), due_job(form))
    assert job.status == core.FAILED and b.print_calls == ["auto"] and "refused" in job.message


def test_timeout_while_sending_is_not_retried_and_warns_it_may_be_on_the_printer(tmp_path, form):
    b = Backend(print_errors=[TimeoutError("timed out")])
    job = run(scheduler(tmp_path, b), due_job(form))
    assert job.status == core.FAILED and b.print_calls == ["now"]
    assert "may already be on the printer" in job.message


def test_missing_form_file_fails_clearly(tmp_path, form):
    j = due_job(form)
    form.unlink()
    job = run(scheduler(tmp_path, Backend()), j)
    assert job.status == core.FAILED and "moved or deleted" in job.message


def test_cancel_while_waiting_stops_the_job(tmp_path, form):
    b = Backend(ready_script=[False])
    s = scheduler(tmp_path, b, window_s=30)
    s.add(due_job(form))
    s.tick()
    for _ in range(300):
        if s.jobs[0].status == core.WAITING:
            break
        time.sleep(0.01)
    assert s.jobs[0].status == core.WAITING
    s.cancel("j1")
    time.sleep(0.1)
    assert s.jobs[0].status == core.CANCELLED and not b.print_calls


def test_restart_settles_unfinished_jobs_without_printing(tmp_path, form):
    store = core.JobStore(tmp_path / "j.json")
    old = (datetime.now() - timedelta(hours=1)).isoformat()
    store.save([
        core.Job("w", str(form), "P", old, core.WAITING),
        core.Job("r", str(form), "P", old, core.RUNNING),
        core.Job("p", str(form), "P", old, core.PENDING),
    ])
    b = Backend()
    s = core.Scheduler(store, b)
    states = {j.id: j for j in s.jobs}
    assert states["w"].status == core.MISSED and "nothing was sent" in states["w"].message
    assert states["r"].status == core.FAILED and "check it" in states["r"].message
    assert states["p"].status == core.MISSED
    s.tick()
    assert not b.print_calls


def test_unsaveable_job_list_does_not_crash(tmp_path, form):
    class BrokenStore(core.JobStore):
        def save(self, jobs):
            raise PermissionError("disk is read-only")

    s = core.Scheduler(BrokenStore(tmp_path / "j.json"), Backend())
    s.add(due_job(form))  # must not raise
    assert "Could not save" in s.store_error and len(s.jobs) == 1


def test_backend_without_readiness_support_just_prints(tmp_path, form):
    class Old:
        def list_printers(self, start_server=True):
            return []

        def print_form(self, form_file, printer, job_name, mode="auto"):
            return "ok"

    job = run(scheduler(tmp_path, Old()), due_job(form))
    assert job.status == core.DONE


def test_failed_connect_does_not_leak_the_client(monkeypatch):
    closed = []

    class Preform:
        def connect(self, **kw):
            raise ApiError("SERVER_UNREACHABLE")

    class Client:
        preform = Preform()

        def close(self):
            closed.append(1)

    monkeypatch.setitem(sys.modules, "formlabs_sdk", types.SimpleNamespace(FormlabsClient=Client))
    backend = core.PreFormBackend()
    with pytest.raises(ApiError):
        backend._open(start_server=False)
    assert closed == [1]
