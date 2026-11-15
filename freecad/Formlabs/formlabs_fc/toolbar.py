"""A Formlabs toolbar that is visible in every workbench (Part Design, Assembly, ...), not only in the Formlabs one."""
from __future__ import annotations

from pathlib import Path

try:
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - older shim
    from PySide import QtCore, QtGui  # type: ignore[import-not-found]

    QtWidgets = QtGui

TOOLBAR_NAME = "Formlabs"
_ICON = Path(__file__).resolve().parent.parent / "Resources" / "formlabs.png"


def _run(command: str):
    import FreeCADGui as Gui

    def go() -> None:
        Gui.runCommand(command)

    return go


def install() -> None:
    """Idempotent: adds the toolbar to the main window once."""
    import FreeCADGui as Gui

    from . import commands

    commands.register()
    win = Gui.getMainWindow()
    if win is None or win.findChild(QtWidgets.QToolBar, "FormlabsGlobalToolbar") is not None:
        return
    icon = QtGui.QIcon(str(_ICON))
    bar = QtWidgets.QToolBar(TOOLBAR_NAME, win)
    bar.setObjectName("FormlabsGlobalToolbar")
    bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    send = QtGui.QAction(icon, "Send to Formlabs", bar) if hasattr(QtGui, "QAction") else QtWidgets.QAction(icon, "Send to Formlabs", bar)
    send.setToolTip("Send the selected solids, or every visible solid, to PreForm (opens the Formlabs panel)")
    send.triggered.connect(_run("Formlabs_Send"))
    panel = QtGui.QAction(icon, "Formlabs panel", bar) if hasattr(QtGui, "QAction") else QtWidgets.QAction(icon, "Formlabs panel", bar)
    panel.setToolTip("Material, layer and options")
    panel.triggered.connect(_run("Formlabs_Panel"))
    bar.addAction(send)
    bar.addAction(panel)
    win.addToolBar(bar)
    bar.show()
