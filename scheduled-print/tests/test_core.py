import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402


class FakeBackend:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def list_printers(self):
        return []

    def print_form(self, form_file, printer, job_name):
        self.calls.append((form_file, printer, job_name))
        if self.fail:
            raise RuntimeError("printer offline")
        return "ok"


@pytest.fixture
def form(tmp_path):
    f = tmp_path / "part.form"
    f.write_bytes(b"x")
    return f


def wait(s, status):
    for _ in range(100):
        if all(j.status == status for j in s.jobs):
            return
        time.sleep(0.02)
    raise AssertionError([j.status for j in s.jobs])


def test_new_job_validates(form, tmp_path):
    now = datetime(2030, 1, 1, 12)
    with pytest.raises(ValueError):
        core.new_job(str(tmp_path / "a.stl"), "P", now + timedelta(hours=1), now)
    with pytest.raises(ValueError):
        core.new_job(str(form), "", now + timedelta(hours=1), now)
    with pytest.raises(ValueError):
        core.new_job(str(form), "P", now - timedelta(minutes=1), now)
    assert core.new_job(str(form), "P", now + timedelta(hours=1), now).status == core.PENDING


def test_runs_when_due_and_persists(form, tmp_path):
    store = core.JobStore(tmp_path / "jobs.json")
    be = FakeBackend()
    s = core.Scheduler(store, be)
    when = datetime.now() + timedelta(hours=2)
    s.add(core.new_job(str(form), "Form4-A", when))
    s.tick(datetime.now())
    assert not be.calls  # not due yet
    s.tick(when + timedelta(seconds=1))
    wait(s, core.DONE)
    assert be.calls[0][1] == "Form4-A"
    s.tick(when + timedelta(seconds=2))
    assert len(be.calls) == 1  # never runs twice
    for _ in range(100):  # the file is written just after the in-memory status changes
        if core.JobStore(tmp_path / "jobs.json").load()[0].status == core.DONE:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("DONE was never persisted")


def test_failure_is_recorded(form, tmp_path):
    s = core.Scheduler(core.JobStore(tmp_path / "j.json"), FakeBackend(fail=True))
    when = datetime.now() + timedelta(hours=1)
    s.add(core.new_job(str(form), "P", when))
    s.tick(when)
    wait(s, core.FAILED)
    assert "offline" in s.jobs[0].message


def test_overdue_job_is_missed_not_printed(form, tmp_path):
    store = core.JobStore(tmp_path / "j.json")
    old = core.Job("a", str(form), "P", (datetime.now() - timedelta(hours=3)).isoformat())
    store.save([old])
    be = FakeBackend()
    s = core.Scheduler(store, be)
    s.tick()
    assert s.jobs[0].status == core.MISSED and not be.calls


def test_cancel_and_corrupt_store(form, tmp_path):
    p = tmp_path / "j.json"
    p.write_text("{not json")
    s = core.Scheduler(core.JobStore(p), FakeBackend())
    assert s.jobs == []
    when = datetime.now() + timedelta(hours=1)
    job = core.new_job(str(form), "P", when)
    s.add(job)
    s.cancel(job.id)
    s.tick(when + timedelta(minutes=1))
    assert s.jobs[0].status == core.CANCELLED


def test_job_is_marked_queued_when_printer_was_not_ready(form, tmp_path):
    class NotReady(FakeBackend):
        def print_form(self, *args):
            return core.PrintOutcome("waiting on the printer", started=False)

    s = core.Scheduler(core.JobStore(tmp_path / "j.json"), NotReady())
    when = datetime.now() + timedelta(hours=1)
    s.add(core.new_job(str(form), "P", when))
    s.tick(when)
    wait(s, core.QUEUED)
    assert "waiting" in s.jobs[0].message
