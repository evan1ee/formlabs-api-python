"""Service entry point. Usage: python -m formlabs_sw_service --project <folder> --preform-exe <path>

The bearer token comes from FL_SERVICE_TOKEN (never argv). Prints one handshake line {"port": N}.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading

from . import errors
from .core import ProjectService
from .errors import ServiceError
from .http_api import make_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--preform-exe", required=True)
    ap.add_argument("--idle-timeout", type=float, default=0, help="seconds; 0 disables")
    args = ap.parse_args(argv)
    token = os.environ.get("FL_SERVICE_TOKEN")
    if not token:
        print(json.dumps({"error": errors.SERVICE_AUTH_FAILED}), flush=True)
        return 2
    from .sdk_adapter import SdkAdapter

    try:
        adapter, close_preform = (
            SdkAdapter.connect() if args.preform_exe == "connect" else SdkAdapter.launch(args.preform_exe)
        )  # "connect" = attach to a server already listening (never terminated)
        svc = ProjectService(args.project, adapter)
        svc.connect()
        svc.recover()  # reconcile journal entries left open by a crash (spec §12.2)
    except ServiceError as exc:
        print(json.dumps(exc.to_dict()), flush=True)
        return 3
    server = make_server(svc, token)
    print(json.dumps({"port": server.server_address[1]}), flush=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        sys.stdin.read()  # the add-in closing our stdin means SOLIDWORKS exited
    finally:
        server.shutdown()
        svc.cancel_autosave()
        svc.save_all()  # safe save before shutdown (spec §2.4)
        close_preform()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
