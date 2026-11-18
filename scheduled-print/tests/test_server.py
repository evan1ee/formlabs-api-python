import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402


def test_find_server_exe_prefers_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STANDALONE_DIR", tmp_path / "none")
    exe = tmp_path / "PreFormServer.exe"
    exe.write_bytes(b"x")
    monkeypatch.delenv("FL_PREFORM_SERVER_EXE", raising=False)
    assert core.find_server_exe(str(exe)) == str(exe)
    assert core.find_server_exe(str(tmp_path / "missing.exe")) in ("", core.find_server_exe())


def test_find_server_exe_from_env_and_program_files(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STANDALONE_DIR", tmp_path / "none")
    exe = tmp_path / "x" / "PreFormServer.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    monkeypatch.setenv("FL_PREFORM_SERVER_EXE", str(exe))
    assert core.find_server_exe("") == str(exe)
    monkeypatch.delenv("FL_PREFORM_SERVER_EXE")
    newer = tmp_path / "Formlabs" / "PreForm" / "3.66" / "PreFormServer.exe"
    newer.parent.mkdir(parents=True)
    newer.write_bytes(b"x")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", "")
    assert core.find_server_exe("") == str(newer)


def test_settings_round_trip(tmp_path):
    s = core.Settings(tmp_path / "s.json")
    assert s.get("server_exe") == ""
    s.set("server_exe", "C:/a.exe")
    s.set("other", "1")
    assert core.Settings(tmp_path / "s.json").get("server_exe") == "C:/a.exe"


class FakePreform:
    def __init__(self):
        self.calls = []

    def launch(self, exe, **kw):
        self.calls.append(("launch", exe, kw))
        return "api"

    def connect(self, **kw):
        self.calls.append(("connect", kw))
        return "api"


def _backend(monkeypatch, exe):
    fake = FakePreform()
    monkeypatch.setitem(sys.modules, "formlabs_sdk", types.SimpleNamespace(FormlabsClient=lambda: types.SimpleNamespace(preform=fake)))
    monkeypatch.setattr(core, "find_server_exe", lambda configured="": configured)
    return fake, core.PreFormBackend(port=1234, server_exe=lambda: exe)


def test_backend_launches_server_when_exe_known(monkeypatch):
    fake, backend = _backend(monkeypatch, "C:/PreFormServer.exe")
    backend._open()
    kind, exe, kw = fake.calls[0]
    assert (kind, exe, kw["reuse_existing"], kw["port"]) == ("launch", "C:/PreFormServer.exe", True, 1234)


def test_backend_connects_when_no_exe(monkeypatch):
    fake, backend = _backend(monkeypatch, "")
    backend._open()
    assert fake.calls == [("connect", {"port": 1234})]


def test_start_server_requires_exe(monkeypatch):
    _, backend = _backend(monkeypatch, "")
    monkeypatch.setattr(backend, "server_reachable", lambda: False)
    try:
        backend.start_server()
    except ValueError as exc:
        assert "PreFormServer.exe" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_start_then_stop_owns_and_closes(monkeypatch):
    closed = []

    class Client:
        def __init__(self):
            self.preform = types.SimpleNamespace(launch=lambda exe, **kw: closed.append(("launch", exe, kw)))

        def close(self):
            closed.append("close")

    monkeypatch.setitem(sys.modules, "formlabs_sdk", types.SimpleNamespace(FormlabsClient=Client))
    monkeypatch.setattr(core, "find_server_exe", lambda configured="": configured)
    backend = core.PreFormBackend(port=9, server_exe=lambda: "C:/PreFormServer.exe")
    monkeypatch.setattr(backend, "server_reachable", lambda: False)
    backend.start_server()
    assert backend.owns_server()
    backend.start_server()  # second call is a no-op
    backend.stop_server()
    assert not backend.owns_server()
    assert closed == [("launch", "C:/PreFormServer.exe", {"port": 9}), "close"]


def test_stop_never_touches_external_server(monkeypatch):
    _, backend = _backend(monkeypatch, "C:/x.exe")
    backend.stop_server()  # nothing owned: must not raise
    assert not backend.owns_server()


def test_find_server_exe_standalone_nested_folder(tmp_path, monkeypatch):
    exe = tmp_path / "PreFormServer" / "PreFormServer.exe"  # how the Formlabs zip unpacks
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    monkeypatch.delenv("FL_PREFORM_SERVER_EXE", raising=False)
    monkeypatch.setattr(core, "STANDALONE_DIR", tmp_path)
    assert core.find_server_exe("") == str(exe)


def test_server_is_spawned_without_a_console_window(monkeypatch):
    import asyncio

    seen = {}

    async def fake(program, *args, **kwargs):
        seen.update(program=program, **kwargs)

    monkeypatch.setattr(core, "_real_create_subprocess_exec", fake)
    asyncio.run(core._spawn_without_console("C:/x/PreFormServer.exe", "--port", "1"))
    seen.clear()
    asyncio.run(core._spawn_without_console("C:/x/other.exe"))
    assert seen["program"] == "C:/x/other.exe" and "creationflags" not in seen  # only the server is changed
    asyncio.run(core._spawn_without_console("C:/x/PreFormServer.exe"))
    assert seen["creationflags"] == core._CREATE_NO_WINDOW


class _Device:
    def __init__(self, **d):
        self._d = d

    def to_dict(self):
        return self._d


def _api(devices):
    return types.SimpleNamespace(list_devices=lambda: types.SimpleNamespace(devices=[_Device(**d) for d in devices]))


def test_printer_ready_by_name_or_ip():
    api = _api([{"id": "A", "ip_address": "10.0.0.5", "ready_to_print_now": True}, {"id": "B", "ready_to_print_now": False}])
    assert core.PreFormBackend._printer_ready(api, "A") is True
    assert core.PreFormBackend._printer_ready(api, "10.0.0.5") is True
    assert core.PreFormBackend._printer_ready(api, "B") is False
    assert core.PreFormBackend._printer_ready(api, "unknown") is None


def test_print_form_reports_queue_only_when_not_ready(monkeypatch, tmp_path):
    calls = []

    class Api:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def open_form_file(self, file):
            return types.SimpleNamespace(scenes=[types.SimpleNamespace(scene_id="s1")])

        def print_scene(self, **kw):
            calls.append(kw)

        def delete_scene(self, scene_id):
            calls.append(("delete", scene_id))

        def list_devices(self):
            return types.SimpleNamespace(devices=[_Device(id="P", ready_to_print_now=False)])

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    backend = core.PreFormBackend()
    monkeypatch.setattr(backend, "_open", lambda start_server=True: (Client(), Api()))
    outcome = backend.print_form("x.form", "P", "job")
    assert outcome.started is False and "NOT start" in outcome.message
    assert calls[0]["printer"] == "P" and ("delete", "s1") in calls
