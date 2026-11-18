import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402


def test_find_server_exe_prefers_configured(tmp_path, monkeypatch):
    exe = tmp_path / "PreFormServer.exe"
    exe.write_bytes(b"x")
    monkeypatch.delenv("FL_PREFORM_SERVER_EXE", raising=False)
    assert core.find_server_exe(str(exe)) == str(exe)
    assert core.find_server_exe(str(tmp_path / "missing.exe")) in ("", core.find_server_exe())


def test_find_server_exe_from_env_and_program_files(tmp_path, monkeypatch):
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
