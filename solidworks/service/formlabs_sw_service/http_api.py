"""Localhost HTTP API with per-session bearer token (spec §2.4, D-03, §13).

The add-in starts this process, passes the token via the FL_SERVICE_TOKEN env var (never argv),
and reads one handshake JSON line from stdout: {"port": N}.
"""

from __future__ import annotations

import hmac
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import errors
from .core import ProjectService, SendRequest
from .errors import ServiceError
from .models import Lock, to_plain


class Operations:
    """Async operation tracking: long calls return an id the add-in polls."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)  # PreForm calls are serialised
        self._ops: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], Any]) -> str:
        op_id = uuid.uuid4().hex
        with self._lock:
            self._ops[op_id] = {"state": "RUNNING", "result": None, "error": None}

        def run() -> None:
            try:
                res = fn()
                out = {"state": "SUCCEEDED", "result": res, "error": None}
            except ServiceError as exc:
                out = {"state": "FAILED", "result": None, "error": exc.to_dict()}
            except Exception as exc:  # noqa: BLE001
                out = {"state": "FAILED", "result": None, "error": {"app_code": "INTERNAL", "message": str(exc)}}
            with self._lock:
                self._ops[op_id] = out

        self._pool.submit(run)
        return op_id

    def get(self, op_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._ops.get(op_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


def _lock_of(v: str | None) -> Lock:
    try:
        return Lock(v) if v else Lock.ROTATION_LOCKED
    except ValueError:
        raise ServiceError(errors.BAD_REQUEST, f"unknown lock {v!r}") from None


def _send_request(body: dict[str, Any]) -> SendRequest:
    try:
        return SendRequest(**{**body, "lock_mode": _lock_of(body.get("lock_mode"))})
    except TypeError as exc:
        raise ServiceError(errors.BAD_REQUEST, str(exc)) from exc


def make_server(svc: ProjectService, token: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("the service binds to 127.0.0.1 only")
    ops = Operations()

    def routes() -> dict[tuple[str, str], Callable[[dict[str, Any]], Any]]:
        return {
            ("GET", "/health"): lambda b: {"ok": True, "server_version": svc.server_version},
            ("POST", "/connect"): lambda b: svc.connect(),
            ("POST", "/send"): lambda b: {"operation_id": ops.submit(lambda: svc.send_model(_send_request(b)))},
            ("POST", "/build/save"): lambda b: to_plain(svc.save_build(b["build_id"])),
            ("POST", "/build/supports"): lambda b: {
                "operation_id": ops.submit(lambda: to_plain(svc.generate_supports(b["build_id"], b.get("params"))))
            },
            ("POST", "/build/layout"): lambda b: {
                "operation_id": ops.submit(lambda: to_plain(svc.layout(b["build_id"])))
            },
            ("POST", "/build/validate"): lambda b: {"operation_id": ops.submit(lambda: svc.validate(b["build_id"]))},
            ("POST", "/build/ack"): lambda b: to_plain(svc.acknowledge_warnings(b["build_id"], b["run_id"])),
            ("POST", "/project/save"): lambda b: {"operation_id": ops.submit(svc.save_project)},
            ("GET", "/project"): lambda b: {"name": svc.project.name, "folder": str(svc.folder)},
            ("GET", "/builds"): lambda b: [to_plain(x) for x in svc.store.builds()],
            ("GET", "/printers"): lambda b: svc.list_printers(),
            ("POST", "/build/submit"): lambda b: {
                "operation_id": ops.submit(
                    lambda: to_plain(
                        svc.submit_build(b["build_id"], b["printer"], b["job_name"], confirmed=b.get("confirmed") is True)
                    )
                )
            },
            ("GET", "/jobs"): lambda b: [to_plain(j) for j in svc.store.jobs_of()],
        }

    table = routes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # no stderr noise; logs go to the project log
            pass

        def _reply(self, code: int, payload: Any) -> None:
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got, f"Bearer {token}")

        def _handle(self, method: str) -> None:
            if not self._authorized():
                return self._reply(401, {"app_code": errors.SERVICE_AUTH_FAILED})
            path = self.path.split("?")[0]
            try:
                if method == "GET" and path.startswith("/operation/"):
                    op = ops.get(path.rsplit("/", 1)[1])
                    return self._reply(200, op) if op else self._reply(404, {"app_code": errors.NOT_FOUND})
                fn = table.get((method, path))
                if fn is None:
                    return self._reply(404, {"app_code": errors.NOT_FOUND})
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                self._reply(200, fn(body))
            except ServiceError as exc:
                self._reply(400, exc.to_dict())
            except (KeyError, json.JSONDecodeError) as exc:
                self._reply(400, {"app_code": errors.BAD_REQUEST, "message": str(exc)})

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

    server = ThreadingHTTPServer((host, port), Handler)
    server.fl_ops = ops  # type: ignore[attr-defined]
    return server
