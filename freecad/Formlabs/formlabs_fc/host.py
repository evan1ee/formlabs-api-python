"""Starts and supervises the Python Integration Service as a child process (token via environment, never argv)."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
from pathlib import Path

from .client import ServiceClient, ServiceError


class ServiceHost:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self.client: ServiceClient | None = None
        self._connected_client: ServiceClient | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, python_exe: Path, project: Path, preform_exe: str, install_dir: Path, timeout: float = 90.0,
              extra_args: tuple[str, ...] = ()) -> None:
        if not python_exe.exists():
            raise ServiceError("SERVICE_START_FAILED", f"missing runtime {python_exe}")
        token = secrets.token_urlsafe(32)
        env = {**os.environ, "FL_SERVICE_TOKEN": token, "PYTHONPATH": str(install_dir)}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [str(python_exe), "-I", "-m", "formlabs_sw_service", "--project", str(project),
             "--preform-exe", preform_exe, *extra_args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, cwd=str(install_dir), creationflags=flags,
        )  # closing stdin tells the service to shut down
        self._proc = proc
        line: list[bytes] = []
        t = threading.Thread(target=lambda: line.append(proc.stdout.readline()), daemon=True)
        t.start()
        t.join(timeout)
        text = line[0].decode("utf-8", "replace").strip() if line else ""
        try:
            hs = json.loads(text or "{}")
        except ValueError:
            hs = {}
        if "port" not in hs:
            self.stop()
            raise ServiceError(hs.get("app_code") or hs.get("error") or "SERVICE_START_FAILED",
                               hs.get("message") or text or f"no handshake within {timeout:.0f}s")
        self.client = ServiceClient(int(hs["port"]), token)
        self._connected_client = None

    def ensure_connected(self, python_exe: Path, project: Path, preform_exe: str, install_dir: Path) -> ServiceClient:
        """Starts the service and connects it to PreForm if needed, so the user never presses Connect."""
        if not self.running:
            project.mkdir(parents=True, exist_ok=True)
            self.start(python_exe, project, preform_exe, install_dir)
        assert self.client is not None
        if self._connected_client is not self.client:
            self.client.post("/connect")
            self._connected_client = self.client
        return self.client

    def stop(self) -> None:
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            p.stdin.close()
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001 - already gone or stuck: kill
            p.kill()
