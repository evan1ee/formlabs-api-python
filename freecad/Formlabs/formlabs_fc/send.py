"""The Send flow: export (GUI thread) -> /send per body -> save -> supports -> layout (worker thread).

A failure in supports or layout is reported in the status text and never undoes the send.
"""
from __future__ import annotations

import queue
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import constants as C
from .client import ServiceClient, ServiceError
from .exporter import ExportedBody
from .host import ServiceHost
from .settings import Settings


@dataclass(frozen=True)
class SendResult:
    sent: int
    note: str  # appended to the status line: what happened to supports and layout

    @property
    def text(self) -> str:
        return f"Sent {self.sent} part(s) to Formlabs.{self.note}"


class Sender:
    def __init__(self, settings: Settings, host: ServiceHost,
                 connect: Callable[[], ServiceClient] | None = None) -> None:
        self.settings = settings
        self.host = host
        self._connect = connect or self._default_connect
        self.log: Callable[[str], None] = lambda _m: None

    def _default_connect(self) -> ServiceClient:
        s = self.settings
        return self.host.ensure_connected(s.install_dir / "python" / "python.exe", s.project_dir(),
                                          s.preform_exe, s.install_dir)

    def send(self, bodies: list[ExportedBody], cancelled: Callable[[], bool] | None = None) -> SendResult:
        s = self.settings
        client = self._connect()
        exports = Path(client.get("/project")["folder"]) / "exports"  # the running service decides the project
        exports.mkdir(parents=True, exist_ok=True)
        changed: list[str] = []
        for b in bodies:
            target = exports / f"{b.body_id}_{uuid.uuid4().hex[:8]}{b.file.suffix}"
            shutil.move(str(b.file), target)
            req = {
                "document": b.doc_path, "configuration": b.config, "body_id": b.body_id, "body_name": b.body_name,
                "export_file": str(target), "export_format": s.export_format, "lock_mode": s.lock_mode,
                "machine_type": C.MACHINE_TYPE, "material_code": s.material,
                "layer_thickness_mm": float(s.layer), "print_setting": "",  # empty: the service picks the catalog default
                "print_cs_transform": b.transform,
            }
            op = client.post("/send", req)
            done = client.wait(op["operation_id"], cancelled=cancelled)
            res = done.get("result") or {}
            if res.get("action") != "unchanged" and res.get("build_id") and res["build_id"] not in changed:
                changed.append(res["build_id"])
        return SendResult(len(bodies), self._auto_prepare(client, changed))

    def _auto_prepare(self, client: ServiceClient, build_ids: list[str]) -> str:
        note = ""
        for bid in build_ids:
            # Save first: the build continues in its saved file (PreForm shows its real name) and layout is reliable.
            try:
                client.post("/build/save", {"build_id": bid})
            except Exception as exc:  # noqa: BLE001
                self.log(f"save before supports FAILED: {exc}")
            ok, why = self._step(client, "/build/supports", bid, "Supports could not be generated", "use Generate supports in PreForm")
            if not ok:
                note = why
                continue  # layout after a failed support step would hide the real problem
            ok, why = self._step(client, "/build/layout", bid, "Auto layout could not be done", "use Auto layout in PreForm")
            note = " Supports generated and parts laid out." if ok and not note else (note or why)
        return note

    def _step(self, client: ServiceClient, path: str, build_id: str, fail: str, fix: str) -> tuple[bool, str]:
        try:
            op = client.post(path, {"build_id": build_id})
            client.wait(op["operation_id"], timeout=1800)
            return True, ""
        except Exception as exc:  # noqa: BLE001
            self.log(f"{path} FAILED: {exc}")
            return False, f" {fail} ({exc}); {fix}."


class BackgroundSend:
    """Runs Sender.send on a worker thread; the GUI polls `poll()` from a timer and never blocks."""

    def __init__(self, sender: Sender) -> None:
        self._sender = sender
        self._q: queue.Queue[str] = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, bodies: list[ExportedBody]) -> None:
        if self.busy:
            raise RuntimeError("A send is already running.")
        self._cancel.clear()

        def work() -> None:
            try:
                self._q.put(self._sender.send(bodies, self._cancel.is_set).text)
            except InterruptedError:
                self._q.put("Stopped waiting. PreForm may still finish the work.")
            except ServiceError as exc:
                self._q.put(f"Send failed: {friendly(exc)}")
            except Exception as exc:  # noqa: BLE001 - every failure must reach the status line
                self._q.put(f"Send failed: {exc}")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def poll(self) -> str | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None


def friendly(exc: ServiceError) -> str:
    if exc.app_code == "PREFORM_NOT_RUNNING":
        return "PreForm is not running. Start PreForm and its server, then send again."
    return str(exc)
