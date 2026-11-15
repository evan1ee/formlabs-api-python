from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "freecad" / "Formlabs"))
sys.path.insert(0, str(ROOT / "solidworks" / "service"))


def _load_service_fakes():
    spec = importlib.util.spec_from_file_location("sw_service_conftest", ROOT / "solidworks" / "service" / "tests" / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def live_service(tmp_path):
    """The real Integration Service over real HTTP, with an in-memory PreForm."""
    from formlabs_sw_service.core import ProjectService
    from formlabs_sw_service.http_api import make_server

    fakes = _load_service_fakes()
    port = fakes.FakePort()
    svc = ProjectService(tmp_path / "proj", port, autosave=False)
    svc.connect()
    server = make_server(svc, "test-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], svc, port
    server.shutdown()
