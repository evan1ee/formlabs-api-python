"""HTTP client for the Integration Service. Loopback only, bearer token on every request."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable


class ServiceError(Exception):
    def __init__(self, app_code: str, message: str = "") -> None:
        super().__init__(f"{app_code}: {message}" if message else app_code)
        self.app_code = app_code
        self.detail = message


class ServiceClient:
    def __init__(self, port: int, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ValueError("token required")
        self._base = f"http://127.0.0.1:{port}"  # loopback only
        self._token = token
        self._timeout = timeout

    def get(self, path: str) -> Any:
        return self.request("GET", path, None)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body if body is not None else {})

    def request(self, method: str, path: str, body: Any) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self._base + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 - loopback http
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                d = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                d = {}
            raise ServiceError(d.get("app_code") or f"HTTP_{exc.code}", d.get("message", "")) from None

    def wait(self, operation_id: str, timeout: float = 600.0, poll: float = 0.2,
             cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Polls an async operation until it leaves RUNNING. Never reports success early."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            op = self.get("/operation/" + operation_id)
            if op["state"] != "RUNNING":
                if op["state"] == "FAILED":
                    e = op.get("error") or {}
                    raise ServiceError(e.get("app_code", "FAILED"), e.get("message", ""))
                return op
            time.sleep(poll)
        raise TimeoutError(f"operation {operation_id} still running")
