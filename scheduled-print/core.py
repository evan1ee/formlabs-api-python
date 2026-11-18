"""Scheduling core: persisted jobs, a due-time runner, and the PreForm backend. No GUI code here."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

GRACE = timedelta(minutes=10)  # a job overdue by more than this (app was closed) is marked missed, never printed late
PENDING, RUNNING, DONE, FAILED, MISSED, CANCELLED = "pending", "running", "done", "failed", "missed", "cancelled"


@dataclass(frozen=True)
class Job:
    id: str
    form_file: str
    printer: str
    run_at: str  # ISO local time
    status: str = PENDING
    message: str = ""

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.run_at)


class Backend(Protocol):
    def list_printers(self) -> list[dict]: ...
    def print_form(self, form_file: str, printer: str, job_name: str) -> str: ...


def new_job(form_file: str, printer: str, run_at: datetime, now: datetime | None = None) -> Job:
    now = now or datetime.now()
    path = Path(form_file)
    if path.suffix.lower() != ".form" or not path.is_file():
        raise ValueError(f"Not a .form file: {form_file}")
    if not printer.strip():
        raise ValueError("Select a printer.")
    if run_at <= now:
        raise ValueError("The scheduled time is in the past.")
    return Job(uuid.uuid4().hex[:8], str(path.resolve()), printer.strip(), run_at.isoformat(timespec="minutes"))


class JobStore:
    """JSON file of jobs, written atomically so a crash never corrupts the schedule."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> list[Job]:
        try:
            return [Job(**row) for row in json.loads(self.path.read_text("utf-8"))]
        except FileNotFoundError:
            return []
        except (ValueError, TypeError):
            self.path.replace(self.path.with_suffix(".corrupt"))  # keep it for inspection, start clean
            return []

    def save(self, jobs: list[Job]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(j) for j in jobs], indent=2), "utf-8")
            for attempt in range(10):  # Windows refuses the swap while a reader or scanner has the file open
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05)


class Scheduler:
    def __init__(self, store: JobStore, backend: Backend, on_change: Callable[[], None] = lambda: None):
        self.store, self.backend, self.on_change = store, backend, on_change
        self._lock = threading.RLock()
        self.jobs = store.load()
        self.expire_missed(datetime.now())

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            self.jobs = [replace(j, **fields) if j.id == job_id else j for j in self.jobs]
            self.store.save(self.jobs)
        self.on_change()

    def add(self, job: Job) -> None:
        with self._lock:
            self.jobs = [*self.jobs, job]
            self.store.save(self.jobs)
        self.on_change()

    def cancel(self, job_id: str) -> None:
        if any(j.id == job_id and j.status == PENDING for j in self.jobs):
            self._update(job_id, status=CANCELLED)

    def remove(self, job_id: str) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.id != job_id or j.status in (PENDING, RUNNING)]
            self.store.save(self.jobs)
        self.on_change()

    def expire_missed(self, now: datetime) -> None:
        for j in list(self.jobs):
            if j.status in (PENDING, RUNNING) and now - j.when > GRACE:
                self._update(j.id, status=MISSED, message="The app was not running at the scheduled time; nothing was printed.")

    def due(self, now: datetime) -> list[Job]:
        return [j for j in self.jobs if j.status == PENDING and j.when <= now]

    def tick(self, now: datetime | None = None) -> None:
        """Run every job that is due. Call about once a second."""
        now = now or datetime.now()
        self.expire_missed(now)
        for job in self.due(now):
            self._update(job.id, status=RUNNING, message="Preparing and sending to the printer...")
            threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: Job) -> None:
        try:
            msg = self.backend.print_form(job.form_file, job.printer, Path(job.form_file).stem)
            self._update(job.id, status=DONE, message=msg)
        except Exception as exc:  # report every failure on the job; never kill the runner
            self._update(job.id, status=FAILED, message=str(getattr(exc, "message", exc))[:300])

    def has_pending(self) -> bool:
        return any(j.status in (PENDING, RUNNING) for j in self.jobs)


class PreFormBackend:
    """Talks to a running PreForm Server (PreForm > File > Start PreForm Server, port 44388)."""

    def __init__(self, port: int = 44388):
        self.port = port

    def _open(self):
        from formlabs_sdk import FormlabsClient  # imported lazily so the core is testable without the SDK

        client = FormlabsClient()
        return client, client.preform.connect(port=self.port)

    def list_printers(self) -> list[dict]:
        client, api = self._open()
        with client, api:
            found = [d.to_dict() for d in api.list_devices().devices]
        return [
            d for d in found
            if d.get("is_connected") and d.get("product_name") == "Form 4" and d.get("connection_type") != "VIRTUAL"
        ]

    def print_form(self, form_file: str, printer: str, job_name: str) -> str:
        client, api = self._open()
        scene_ids: list[str] = []
        with client, api:
            try:
                opened = api.open_form_file(file=form_file)
                scene_ids = [str(s.scene_id) for s in opened.scenes]
                if not scene_ids:
                    raise RuntimeError("The .form file has no scenes.")
                # No print_now: prints immediately when the printer is ready, otherwise queues on it.
                api.print_scene(scene_id=scene_ids[0], printer=printer, job_name=job_name, find_printer_timeout_seconds=30)
            finally:
                for sid in scene_ids:
                    api.delete_scene(scene_id=sid)
        return f"Sent to {printer} at {datetime.now():%H:%M}."
