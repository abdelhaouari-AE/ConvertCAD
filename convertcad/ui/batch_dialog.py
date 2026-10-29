"""
batch_dialog.py — convert every PDF of a folder in one run.

Uses the current settings. Calibration does not apply here: each sheet uses
the scale written in its title block when "Read the scale written on each
sheet" is ticked (default), otherwise the drawing scale of the settings.
Runs in a background process; each file gets its DXF (or DWG, following
Settings > Output > File format) and its _log.txt in the output folder
(sub-folders mirrored).
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QGridLayout,
                               QHeaderView, QLineEdit, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..core.jobs import JobRunner
from ..core.paths import find_pdfs
from ..i18n import tr, tr_progress
from . import theme
from .dialogs import open_folder
from .icons import icon
from .widgets import label


class BatchDialog(QDialog):
    def __init__(self, settings, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Convert a folder"))
        self.resize(780, 560)
        self.settings = settings
        self.options = options
        self.options.calibrated_units_per_pt = 0.0
        self.options.pages = None
        self.options.clip_rect = None
        self.runner = JobRunner()
        self.files = []
        self.ok = self.failed = 0
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._poll)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.in_edit = QLineEdit(settings.last_batch_in)
        self.out_edit = QLineEdit(settings.last_batch_out)
        for r, (text, edit, slot) in enumerate((
                (tr("Folder of PDF drawings"), self.in_edit, self._pick_in),
                (tr("Output folder"), self.out_edit, self._pick_out))):
            grid.addWidget(label(text, "muted"), r, 0)
            grid.addWidget(edit, r, 1)
            b = QPushButton(icon("folder"), tr("Browse…"))
            b.clicked.connect(slot)
            grid.addWidget(b, r, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.recursive = QCheckBox(tr("Include sub-folders"))
        self.recursive.toggled.connect(self._scan)
        lay.addWidget(self.recursive)
        self.auto_scale = QCheckBox(tr("Read the scale written on each sheet"))
        self.auto_scale.setChecked(True)
        self.auto_scale.setToolTip(tr(
            "Each sheet uses the scale of its title block (1:100, 1/50…); "
            "the drawing scale of the settings is used when a sheet shows "
            "none, or several."))
        lay.addWidget(self.auto_scale)
        fmt = "DWG" if options.output_format == "dwg" else "DXF"
        lay.addWidget(label(tr("Uses the current settings (files saved as "
                               "{fmt}). Calibration and area do not apply in "
                               "this mode: check the scale of each sheet in "
                               "its log.", fmt=fmt), "caption", wrap=True))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("File"), tr("Status"),
                                              tr("Time")])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)
        self.info = label("", "muted", wrap=True)
        lay.addWidget(self.info)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        lay.addWidget(self.progress)
        box = QDialogButtonBox()
        self.btn_open = box.addButton(tr("Open the output folder"),
                                      QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(lambda: open_folder(self.out_edit.text()))
        self.btn_start = box.addButton(tr("Start"),
                                       QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_start.setProperty("kind", "primary")
        self.btn_close = box.addButton(tr("Close"),
                                       QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_start.clicked.connect(self._start_or_cancel)
        self.btn_close.clicked.connect(self.reject)
        lay.addWidget(box)
        self.in_edit.editingFinished.connect(self._scan)
        self._scan()

    # ---------------------------------------------------------------------
    def _pick_in(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Choose a folder"),
                                             self.in_edit.text())
        if d:
            self.in_edit.setText(d)
            if not self.out_edit.text():
                self.out_edit.setText(os.path.join(
                    d, "DWG" if self.options.output_format == "dwg" else "DXF"))
            self._scan()

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Choose a folder"),
                                             self.out_edit.text()
                                             or self.in_edit.text())
        if d:
            self.out_edit.setText(d)

    def _scan(self) -> None:
        folder = self.in_edit.text().strip()
        self.files = find_pdfs(folder, self.recursive.isChecked()) \
            if folder and os.path.isdir(folder) else []
        self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            rel = os.path.relpath(f, folder)
            self.table.setItem(i, 0, QTableWidgetItem(rel))
            self.table.setItem(i, 1, QTableWidgetItem(tr("Waiting")))
            self.table.setItem(i, 2, QTableWidgetItem(""))
        if folder and not self.files:
            self.info.setText(tr("No PDF file in this folder."))
        elif self.files:
            self.info.setText(tr("{n} PDF file(s) found.", n=len(self.files)))
        else:
            self.info.setText("")
        self.btn_start.setEnabled(bool(self.files))

    def _set_status(self, row: int, text: str, color: str = "") -> None:
        it = self.table.item(row, 1)
        if it is None:
            return
        it.setText(text)
        if color:
            from PySide6.QtGui import QColor
            it.setForeground(QColor(color))

    # ---------------------------------------------------------------------
    def _start_or_cancel(self) -> None:
        if self.runner.is_running():
            self.runner.cancel()
            self.info.setText(tr("Cancelling…"))
            return
        out = self.out_edit.text().strip()
        if not self.files or not out:
            return
        self.settings.last_batch_in = self.in_edit.text().strip()
        self.settings.last_batch_out = out
        self.settings.save()
        self.ok = self.failed = 0
        for i in range(len(self.files)):
            self._set_status(i, tr("Waiting"), theme.tok("text_muted"))
            self.table.item(i, 2).setText("")
        self._set_status(0, tr("Converting"), theme.tok("accent"))
        self.progress.setValue(0)
        self.progress.show()
        self.options.auto_scale = self.auto_scale.isChecked()
        self.runner.start_batch(self.in_edit.text().strip(), out,
                                self.options.to_dict(), files=self.files)
        self.btn_start.setText(tr("Cancel"))
        self.btn_start.setProperty("kind", "danger")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)
        self.btn_close.setEnabled(False)
        self.timer.start()

    def _poll(self) -> None:
        for msg in self.runner.poll():
            kind = msg[0]
            if kind == "progress":
                self.info.setText(tr_progress(msg[1]))
                self.progress.setValue(int(msg[2] * 1000))
            elif kind == "file":
                i, rep = msg[1], msg[2]
                if rep.success:
                    self.ok += 1
                    self._set_status(i, tr("Done"), theme.tok("ok"))
                else:
                    self.failed += 1
                    self._set_status(i, tr("Failed"), theme.tok("err"))
                    self.table.item(i, 0).setToolTip("\n".join(rep.errors))
                self.table.item(i, 2).setText(f"{rep.duration_s:.1f} s")
                if i + 1 < len(self.files):
                    self._set_status(i + 1, tr("Converting"),
                                     theme.tok("accent"))
            elif kind in ("done", "cancelled", "error"):
                self._finish(kind, msg)

    def _finish(self, kind: str, msg) -> None:
        self.timer.stop()
        self.progress.hide()
        self.btn_start.setText(tr("Start"))
        self.btn_start.setProperty("kind", "primary")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)
        self.btn_close.setEnabled(True)
        self.btn_open.setEnabled(self.ok > 0)
        if kind == "error":
            self.info.setText(str(msg[1]).strip().splitlines()[-1])
        elif kind == "cancelled" or (kind == "done" and msg[1].get("cancelled")):
            self.info.setText(tr("Conversion cancelled.") + "  "
                              + tr("{ok} of {total} converted.", ok=self.ok,
                                   total=len(self.files)))
        else:
            self.info.setText(tr("{ok} of {total} converted.", ok=self.ok,
                                 total=len(self.files)))

    def reject(self) -> None:
        if self.runner.is_running():
            self.runner.cancel(grace_s=0.5)
            return
        self.runner.shutdown()
        super().reject()
