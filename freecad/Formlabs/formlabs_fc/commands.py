"""FreeCAD commands: Formlabs_Send (one click) and Formlabs_Panel (material, layer, options)."""
from __future__ import annotations

import os
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

from . import exporter
from .host import ServiceHost
from .send import BackgroundSend, Sender
from .settings import Settings

_ICON = str(Path(__file__).resolve().parent.parent / "Resources" / "formlabs.png")
_settings = Settings()
_host = ServiceHost()
_sender = Sender(_settings, _host)
_sender.log = lambda m: App.Console.PrintWarning(f"Formlabs: {m}\n")
_bg = BackgroundSend(_sender)
_panel = None


def start_send() -> bool:
    """Exports on the GUI thread, then hands the files to the worker. Raises with a readable message on bad input."""
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError("Open a part or an assembly first.")
    objs = exporter.collect(doc, Gui.Selection.getSelection())
    staging = _settings.project_dir() / "exports" / "staging"
    bodies = exporter.export_objects(doc, objs, staging, _settings.export_format, _settings.orientation,
                                     exporter.view_rotation(Gui))
    _bg.start(bodies)
    return True


class _Send:
    def GetResources(self):  # noqa: N802
        return {"Pixmap": _ICON, "MenuText": "Send to Formlabs",
                "ToolTip": "Send the selected solids, or every visible solid, to PreForm"}

    def IsActive(self):  # noqa: N802
        return App.ActiveDocument is not None and not _bg.busy

    def Activated(self):  # noqa: N802
        _show_panel()
        _panel._on_send()


class _Panel:
    def GetResources(self):  # noqa: N802
        return {"Pixmap": _ICON, "MenuText": "Formlabs panel", "ToolTip": "Material, layer and options"}

    def IsActive(self):  # noqa: N802
        return True

    def Activated(self):  # noqa: N802
        _show_panel()


def _show_panel() -> None:
    global _panel
    from .panel import FormlabsPanel

    if _panel is None or Gui.Control.activeDialog() is False:
        _panel = FormlabsPanel(_settings, start_send)
        _panel.poll = _bg.poll
        _panel.stop.clicked.connect(_bg.cancel)
        Gui.Control.showDialog(_panel)


def register() -> None:
    Gui.addCommand("Formlabs_Send", _Send())
    Gui.addCommand("Formlabs_Panel", _Panel())
