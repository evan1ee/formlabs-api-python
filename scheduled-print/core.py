"""Scheduling core: persisted jobs, a due-time runner, and the PreForm backend. No GUI code here."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

from timefmt import humanize_delta

GRACE = timedelta(minutes=10)  # a job overdue by more than this (app was closed) is marked missed, never printed late
STANDALONE_DIR = Path("C:/PreFormServer")  # where Formlabs's docs put the standalone server
PENDING, WAITING, RUNNING, DONE, QUEUED, FAILED, MISSED, CANCELLED = (
    "pending", "waiting", "running", "done", "queued", "failed", "missed", "cancelled"
)
ACTIVE = (PENDING, WAITING, RUNNING)  # jobs that still need the app to stay open
NEEDS_ATTENTION = (FAILED, QUEUED, MISSED)  # finished, but the print did not start by itself
DEFAULT_WAIT = timedelta(minutes=60)  # how long a due job waits for a not-ready printer before it is only queued
# PreFormApiError codes raised before anything is sent to the printer, so trying again cannot print twice.
NOTHING_SENT = ("SERVER_UNREACHABLE", "NOT_CONNECTED", "STARTUP_FAILED", "PORT_IN_USE")


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


@dataclass(frozen=True)
class PrintOutcome:
    """What happened to a sent job. started=False means the printer was not ready, so the job only waits in its queue."""

    message: str
    started: bool = True


class Backend(Protocol):
    def list_printers(self, start_server: bool = True) -> list[dict]: ...
    def print_form(self, form_file: str, printer: str, job_name: str, mode: str = "auto") -> str | PrintOutcome: ...
    # Optional; a backend without these prints at once and never waits:
    #   printer_ready(printer) -> bool | None   (None = printer not found)
    #   ensure_server() -> None


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


def is_retryable(exc: Exception, sending_now: bool = False) -> bool:
    """True when nothing reached the printer, so trying again later cannot print twice."""
    code = getattr(exc, "code", "")
    return code in NOTHING_SENT or (sending_now and code == "OPERATION_FAILED")  # "now" is refused when not ready


def explain(exc: Exception) -> str:
    """A message for the job list that says what happened and whether the print may have been sent."""
    code, msg = getattr(exc, "code", ""), str(getattr(exc, "message", exc))
    if isinstance(exc, FileNotFoundError):
        return msg
    if code in NOTHING_SENT:
        return f"PreForm Server was not available, so nothing was sent. {msg}"[:300]
    if isinstance(exc, (TimeoutError, OSError)) or type(exc).__module__.startswith("httpx"):
        return f"The connection to PreForm Server was lost while sending ({msg}). The job may already be on the printer: check its queue before scheduling it again."[:300]
    if code == "OPERATION_FAILED":
        return f"The printer or PreForm refused the job: {msg}"[:300]
    return msg[:300]


class Scheduler:
    def __init__(
        self,
        store: JobStore,
        backend: Backend,
        on_change: Callable[[], None] = lambda: None,
        wait_window: Callable[[], timedelta] = lambda: DEFAULT_WAIT,
        poll_seconds: float = 15.0,
    ):
        self.store, self.backend, self.on_change = store, backend, on_change
        self.wait_window, self.poll_seconds = wait_window, poll_seconds
        self.store_error = ""  # set when the job list cannot be saved; the app keeps running and shows it
        self._lock = threading.RLock()
        self.jobs = store.load()
        self.recover_after_restart(datetime.now())

    def _save(self) -> None:
        try:
            self.store.save(self.jobs)
            self.store_error = ""
        except OSError as exc:  # disk full, permissions: keep running from memory rather than crash the timer
            self.store_error = f"Could not save the job list ({exc}). Scheduled prints will be lost if the app closes."

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            self.jobs = [replace(j, **fields) if j.id == job_id else j for j in self.jobs]
            self._save()
        self.on_change()

    def _status(self, job_id: str) -> str:
        return next((j.status for j in self.jobs if j.id == job_id), CANCELLED)

    def add(self, job: Job) -> None:
        with self._lock:
            self.jobs = [*self.jobs, job]
            self._save()
        self.on_change()

    def cancel(self, job_id: str) -> None:
        if any(j.id == job_id and j.status in (PENDING, WAITING) for j in self.jobs):
            self._update(job_id, status=CANCELLED, message="Cancelled.")

    def remove(self, job_id: str) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.id != job_id or j.status in ACTIVE]
            self._save()
        self.on_change()

    def recover_after_restart(self, now: datetime) -> None:
        """Settle jobs a previous run left unfinished. Nothing is ever started late or twice by guessing."""
        for j in list(self.jobs):
            if j.status == WAITING:
                self._update(j.id, status=MISSED, message="The app was closed while waiting for the printer; nothing was sent.")
            elif j.status == RUNNING:
                self._update(j.id, status=FAILED, message="The app was closed while this job was being sent. It may be on the printer's queue: check it before scheduling again.")
            elif j.status == PENDING:
                self.expire_missed(now)

    def expire_missed(self, now: datetime) -> None:
        for j in list(self.jobs):
            if j.status == PENDING and now - j.when > GRACE:
                self._update(j.id, status=MISSED, message="The app was not running at the scheduled time; nothing was printed.")

    def due(self, now: datetime) -> list[Job]:
        return [j for j in self.jobs if j.status == PENDING and j.when <= now]

    def tick(self, now: datetime | None = None) -> None:
        """Run every job that is due. Call about once a second."""
        now = now or datetime.now()
        self.expire_missed(now)
        for job in self.due(now):
            self._update(job.id, status=RUNNING, message="Checking the printer...")
            threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: Job) -> None:
        try:
            self._wait_and_print(job)
        except Exception as exc:  # report every failure on the job; never kill the runner
            self._update(job.id, status=FAILED, message=explain(exc))

    def _finish(self, job: Job, result: str | PrintOutcome) -> None:
        outcome = result if isinstance(result, PrintOutcome) else PrintOutcome(str(result))
        self._update(job.id, status=DONE if outcome.started else QUEUED, message=outcome.message)

    def _wait_and_print(self, job: Job) -> None:
        """Start the job as soon as the printer is ready. While it is not (or PreForm Server is unavailable) keep
        checking until the wait window ends; then queue it on the printer, which will not start it by itself."""
        form = Path(job.form_file)
        if not form.is_file():
            raise FileNotFoundError(f"The .form file was moved or deleted: {job.form_file}")
        name = form.stem
        ready_of = getattr(self.backend, "printer_ready", None)
        if ready_of is None:
            return self._finish(job, self.backend.print_form(job.form_file, job.printer, name))
        ensure = getattr(self.backend, "ensure_server", lambda: None)
        deadline = job.when + self.wait_window()
        while self._status(job.id) in (RUNNING, WAITING):
            sending_now = False
            try:
                ensure()
                ready = ready_of(job.printer)
                if ready is False:
                    if datetime.now() >= deadline:
                        return self._queue_only(job, name)
                    reason = "Printer not ready."
                else:
                    self._update(job.id, status=RUNNING, message="Sending to the printer...")
                    sending_now = ready is True
                    return self._finish(job, self.backend.print_form(job.form_file, job.printer, name, mode="now" if sending_now else "auto"))
            except Exception as exc:
                if not is_retryable(exc, sending_now) or datetime.now() >= deadline:
                    raise
                reason = f"{explain(exc)} Retrying."
            left = max(deadline - datetime.now(), timedelta(0))
            self._update(job.id, status=WAITING, message=f"{reason} It starts as soon as possible (gives up in {humanize_delta(left)}).")
            time.sleep(self.poll_seconds)

    def _queue_only(self, job: Job, name: str) -> None:
        waited = humanize_delta(self.wait_window())
        result = self.backend.print_form(job.form_file, job.printer, name, mode="queue")
        if isinstance(result, PrintOutcome):
            result = PrintOutcome(f"The printer was not ready for {waited}. {result.message}", result.started)
        self._finish(job, result)

    def has_pending(self) -> bool:
        return any(j.status in ACTIVE for j in self.jobs)


_CREATE_NO_WINDOW = 0x08000000
_real_create_subprocess_exec = asyncio.create_subprocess_exec


async def _spawn_without_console(program, *args, **kwargs):
    if os.name == "nt" and Path(str(program)).name.lower() == "preformserver.exe":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
    return await _real_create_subprocess_exec(program, *args, **kwargs)


def hide_server_console() -> None:
    """The SDK starts PreFormServer.exe as a console program, which pops up a terminal window from a GUI app.
    The SDK has no option for this, so wrap process creation to add CREATE_NO_WINDOW for that one program."""
    asyncio.create_subprocess_exec = _spawn_without_console


def find_server_exe(configured: str = "") -> str:
    """The PreFormServer.exe to launch: the configured path, FL_PREFORM_SERVER_EXE, or one under Program Files\\Formlabs."""
    for candidate in (configured, os.environ.get("FL_PREFORM_SERVER_EXE", "")):
        if candidate and Path(candidate).is_file():
            return candidate
    standalone = sorted(STANDALONE_DIR.glob("**/PreFormServer.exe")) if STANDALONE_DIR.is_dir() else []
    if standalone:  # the Formlabs zip unpacks to C:\PreFormServer\PreFormServer\PreFormServer.exe
        return str(standalone[0])
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        base = Path(root) / "Formlabs" if root else None
        if base and base.is_dir():
            found = sorted(base.glob("**/PreFormServer.exe"), reverse=True)  # newest version folder first
            if found:
                return str(found[0])
    return ""


class Settings:
    """Small JSON file next to the job list (currently just the PreFormServer.exe path)."""

    def __init__(self, path: Path):
        self.path = path

    def get(self, key: str, default: str = "") -> str:
        try:
            return str(json.loads(self.path.read_text("utf-8")).get(key, default))
        except (OSError, ValueError, AttributeError):
            return default

    def set(self, key: str, value: str) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**data, key: value}, indent=2), "utf-8")
        os.replace(tmp, self.path)


class PreFormBackend:
    """Talks to a running PreForm Server (PreForm > File > Start PreForm Server, port 44388)."""

    def __init__(self, port: int = 44388, server_exe: Callable[[], str] = lambda: ""):
        self.port = port
        self.server_exe = server_exe  # called each time, so a changed setting applies to the next job
        self._owner = None  # the SDK client that started (and so owns) the server, while the toggle has it on
        self._owner_lock = threading.Lock()

    def server_reachable(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://localhost:{self.port}/v1/", timeout=2):  # noqa: S310 - fixed localhost URL
                return True
        except OSError:
            return False

    def owns_server(self) -> bool:
        return self._owner is not None

    def start_server(self) -> None:
        """Start PreFormServer and keep it running until stop_server(). A server already running is left alone."""
        from formlabs_sdk import FormlabsClient

        hide_server_console()
        with self._owner_lock:
            if self._owner is not None or self.server_reachable():
                return
            exe = find_server_exe(self.server_exe())
            if not exe:
                raise ValueError(
                    "PreFormServer.exe not found. It is a separate download from Formlabs (not part of PreForm): "
                    "unzip it, e.g. to C:/PreFormServer, and set its path below. Or start the server in PreForm: File > Start PreForm Server."
                )
            client = FormlabsClient()
            try:
                client.preform.launch(exe, port=self.port)
            except Exception:
                client.close()
                raise
            self._owner = client

    def stop_server(self) -> None:
        """Stop a server this app started. One started in PreForm itself is never stopped."""
        with self._owner_lock:
            owner, self._owner = self._owner, None
        if owner is not None:
            owner.close()

    def _open(self, start_server: bool = True):
        from formlabs_sdk import FormlabsClient  # imported lazily so the core is testable without the SDK

        client = FormlabsClient()
        hide_server_console()
        try:
            exe = find_server_exe(self.server_exe()) if start_server else ""
            if exe:
                # Use a server that is already running; otherwise start one and stop it when the call is done.
                return client, client.preform.launch(exe, port=self.port, reuse_existing=True)
            return client, client.preform.connect(port=self.port)
        except BaseException:
            client.close()  # a failed connect must not leak the client's event-loop thread
            raise

    def list_printers(self, start_server: bool = True) -> list[dict]:
        client, api = self._open(start_server)
        with client, api:
            found = [d.to_dict() for d in api.list_devices().devices]
        return [
            d for d in found
            if d.get("is_connected") and d.get("product_name") == "Form 4" and d.get("connection_type") != "VIRTUAL"
        ]

    @staticmethod
    def _printer_ready(api, printer: str) -> bool | None:
        """Whether a job sent now would start by itself; None when the printer is not in the device list."""
        for device in api.list_devices().devices:
            d = device.to_dict()
            if printer in (d.get("id"), d.get("ip_address")):
                return bool(d.get("ready_to_print_now"))
        return None

    def printer_ready(self, printer: str) -> bool | None:
        """Whether a job sent now would start by itself; None when the printer is not in the device list."""
        client, api = self._open(start_server=False)  # ensure_server() already started one if this app can
        with client, api:
            return self._printer_ready(api, printer)

    def ensure_server(self) -> None:
        try:
            self.start_server()  # reuses a running server, otherwise starts one and keeps it until stop_server()
        except ValueError:
            pass  # no PreFormServer.exe known: the later calls report that the server is unreachable

    def print_form(self, form_file: str, printer: str, job_name: str, mode: str = "auto") -> PrintOutcome:
        """mode "now" must start at once (the SDK refuses if the printer is not ready), "queue" only queues,
        "auto" lets the printer decide."""
        client, api = self._open()
        scene_ids: list[str] = []
        with client, api:
            try:
                opened = api.open_form_file(file=form_file)
                scene_ids = [str(s.scene_id) for s in opened.scenes]
                if not scene_ids:
                    raise RuntimeError("The .form file has no scenes.")
                # No print_now: prints immediately when the printer is ready, otherwise queues on it.
                ready = self._printer_ready(api, printer) if mode == "auto" else mode == "now"
                extra = {} if mode == "auto" else {"print_now": mode == "now"}
                api.print_scene(scene_id=scene_ids[0], printer=printer, job_name=job_name, find_printer_timeout_seconds=30, **extra)
            finally:
                for sid in scene_ids:
                    api.delete_scene(scene_id=sid)
        note = f" The file has {len(scene_ids)} scenes; only the first was sent." if len(scene_ids) > 1 else ""
        if mode == "queue":
            ready = False
        if ready is False:
            return PrintOutcome(
                f"Queued on {printer} at {datetime.now():%H:%M}, but the printer was not ready, so it will NOT start by itself. "
                "Start it from the printer's screen." + note,
                started=False,
            )
        return PrintOutcome(f"Sent to {printer} at {datetime.now():%H:%M}. It starts automatically." + note)
