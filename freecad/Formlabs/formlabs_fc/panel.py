"""Task panel: material and layer, one Send button, collapsed options. Qt only; the logic lives in send.py."""
from __future__ import annotations

from pathlib import Path

from . import constants as C
from .settings import Settings

try:  # FreeCAD 1.0 ships PySide6, 0.21 PySide2; the shim exposes both as PySide
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - older shim
    from PySide import QtCore, QtGui  # type: ignore[import-not-found]

    QtWidgets = QtGui


class FormlabsPanel:
    """Used with Gui.Control.showDialog(): FreeCAD calls getStandardButtons/accept/reject."""

    def __init__(self, settings: Settings, send_action) -> None:
        self.settings = settings
        self._send_action = send_action  # callable() -> bool, starts a send; False if nothing could start
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Formlabs")
        lay = QtWidgets.QVBoxLayout(self.form)

        self.status = QtWidgets.QLabel("Ready.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        box = QtWidgets.QGroupBox("1. Material and layer")
        form = QtWidgets.QFormLayout(box)
        self.material = QtWidgets.QComboBox()
        for m in C.MATERIALS:
            self.material.addItem(m.name, m.code)
            self.material.setItemData(self.material.count() - 1, m.use, QtCore.Qt.ToolTipRole)
        self.material.setCurrentIndex(max(0, self.material.findData(settings.material)))
        self.use = QtWidgets.QLabel("")
        self.use.setWordWrap(True)
        self.layer = QtWidgets.QComboBox()
        self.layer.addItems([f"{x} mm" for x in C.LAYERS])
        self.layer.setCurrentIndex(C.LAYERS.index(settings.layer))
        form.addRow("Material", self.material)
        form.addRow("", self.use)
        form.addRow("Layer", self.layer)
        lay.addWidget(box)

        self.send = QtWidgets.QPushButton("Send to Formlabs")
        self.send.setStyleSheet("QPushButton { background:#f26b21; color:white; padding:8px; font-weight:bold; }")
        self.send.setToolTip("Sends the selected solids, or every visible solid, to PreForm. "
                             "Then it generates supports and lays the build out.")
        lay.addWidget(self.send)
        self.stop = QtWidgets.QPushButton("Stop waiting")
        self.stop.setVisible(False)
        lay.addWidget(self.stop)
        self.hint = QtWidgets.QLabel("Select parts, or send everything visible. The view you see is how the part lands.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        more = QtWidgets.QGroupBox("More options")
        more.setCheckable(True)
        more.setChecked(False)
        mf = QtWidgets.QFormLayout(more)
        self.orient = QtWidgets.QComboBox()
        self.orient.addItem("As the view shows it", "view")
        self.orient.addItem("Same axes as FreeCAD", "same")
        self.orient.addItem("Stand a Y-up part up", "yup")
        self.orient.setCurrentIndex(max(0, self.orient.findData(settings.orientation)))
        self.freedom = QtWidgets.QComboBox()
        for label, code in (("Keep orientation, allow move", C.LOCK_MODES[0]),
                            ("Keep tilt, allow turning flat", C.LOCK_MODES[1]), ("Free", C.LOCK_MODES[2])):
            self.freedom.addItem(label, code)
        self.freedom.setCurrentIndex(max(0, self.freedom.findData(settings.lock_mode)))
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItems(["STEP", "STL"])
        self.fmt.setCurrentText(settings.export_format)
        mf.addRow("Placement", self.orient)
        mf.addRow("Freedom", self.freedom)
        mf.addRow("Export format", self.fmt)
        lay.addWidget(more)
        for w in (self.orient, self.freedom, self.fmt):
            w.setVisible(False)
        more.toggled.connect(lambda on: [w.setVisible(on) for w in (self.orient, self.freedom, self.fmt)])

        proj = QtWidgets.QGroupBox("Project and connection")
        proj.setCheckable(True)
        proj.setChecked(False)
        pl = QtWidgets.QVBoxLayout(proj)
        self.project = QtWidgets.QLabel(str(settings.project_dir()))
        self.project.setWordWrap(True)
        self.new_project = QtWidgets.QPushButton("New project today")
        pl.addWidget(self.project)
        pl.addWidget(self.new_project)
        for w in (self.project, self.new_project):
            w.setVisible(False)
        proj.toggled.connect(lambda on: [w.setVisible(on) for w in (self.project, self.new_project)])
        lay.addWidget(proj)
        lay.addStretch(1)

        self.material.currentIndexChanged.connect(self._save)
        self.layer.currentIndexChanged.connect(self._save)
        self.orient.currentIndexChanged.connect(self._save)
        self.freedom.currentIndexChanged.connect(self._save)
        self.fmt.currentIndexChanged.connect(self._save)
        self.send.clicked.connect(self._on_send)
        self.new_project.clicked.connect(self._on_new_project)
        self._update_use()
        self.timer = QtCore.QTimer(self.form)
        self.timer.timeout.connect(self._tick)
        self.poll = lambda: None  # set by commands: returns a finished-status text or None

    def _update_use(self) -> None:
        code = self.material.currentData()
        self.use.setText(next((m.use for m in C.MATERIALS if m.code == code), ""))

    def _save(self) -> None:
        s = self.settings
        s.material = self.material.currentData()
        s.layer = C.LAYERS[self.layer.currentIndex()]
        s.orientation = self.orient.currentData()
        s.lock_mode = self.freedom.currentData()
        s.export_format = self.fmt.currentText()
        self._update_use()

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        self.send.setEnabled(not busy)
        self.stop.setVisible(busy)
        if text is not None:
            self.status.setText(text)

    def _on_send(self) -> None:
        self._save()
        self.set_busy(True, "Sending to Formlabs…")
        try:
            started = self._send_action()
        except Exception as exc:  # noqa: BLE001 - export problems are shown, not thrown at FreeCAD
            self.set_busy(False, f"Send failed: {exc}")
            return
        if not started:
            self.set_busy(False, "Nothing was sent.")
            return
        self.timer.start(300)

    def _tick(self) -> None:
        done = self.poll()
        if done is not None:
            self.timer.stop()
            self.set_busy(False, done)

    def _on_new_project(self) -> None:
        self.settings.set_project_dir(self.settings.new_project_folder())
        self.project.setText(str(self.settings.project_dir()))
        self.status.setText("New project started. The next send opens a new build in it.")

    # Gui.Control dialog protocol
    def getStandardButtons(self):  # noqa: N802
        return QtWidgets.QDialogButtonBox.Close

    def reject(self):
        self.timer.stop()
        return True
