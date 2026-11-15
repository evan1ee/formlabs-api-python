"""FreeCAD executes InitGui.py with separate globals and locals and without __file__; this must still load."""
from __future__ import annotations

import sys
import types
from pathlib import Path

MOD = Path(__file__).resolve().parents[1] / "Formlabs"


def test_initgui_loads_the_way_freecad_runs_it(monkeypatch):
    registered = []

    class Workbench:
        pass

    gui = types.ModuleType("FreeCADGui")
    gui.Workbench = Workbench
    gui.addWorkbench = registered.append
    monkeypatch.setitem(sys.modules, "FreeCADGui", gui)
    monkeypatch.syspath_prepend(str(MOD))  # FreeCAD puts the Mod folder on sys.path before running InitGui.py
    code = compile((MOD / "InitGui.py").read_text(encoding="utf-8"), "InitGui.py", "exec")
    exec(code, {"__name__": "InitGui"}, {})  # separate locals, no __file__
    assert registered and registered[0].Icon.endswith("formlabs.png") and Path(registered[0].Icon).exists()
    assert registered[0].MenuText == "Formlabs"
