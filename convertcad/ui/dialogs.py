"""
dialogs.py — Terms of use, About, User guide, Shortcuts, Calibration.

Long texts are Markdown files in convertcad/resources (English and French),
rendered with Qt's built-in Markdown support — edit them in any editor.
"""

import os
import sys

from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout)

from .. import APP_AUTHOR, APP_NAME, APP_VERSION, APP_YEAR
from ..core.constants import PT_TO_MM, UNITS
from ..i18n import language, tr
from .icons import app_icon
from .widgets import label


def resource_path(name: str) -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "resources")
    return os.path.join(base, name)


def read_resource(stem: str) -> str:
    """Markdown resource in the current language (English fallback)."""
    for lang in (language(), "en"):
        p = resource_path(f"{stem}_{lang}.md")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as fh:
                return (fh.read().replace("{APP_VERSION}", APP_VERSION)
                        .replace("{APP_AUTHOR}", APP_AUTHOR)
                        .replace("{APP_YEAR}", APP_YEAR))
    return ""


class MarkdownDialog(QDialog):
    def __init__(self, title: str, stem: str, parent=None, w=760, h=640):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(w, h)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.document().setDocumentMargin(22)
        self.browser.setMarkdown(read_resource(stem))
        lay.addWidget(self.browser)
        self.buttons = QDialogButtonBox()
        lay.addWidget(self.buttons)
        self.buttons.setContentsMargins(0, 0, 12, 0)


class GuideDialog(MarkdownDialog):
    def __init__(self, parent=None, stem: str = "guide"):
        super().__init__(tr("User guide") if stem == "guide"
                         else tr("OCR guide (scanned PDFs)"), stem, parent)
        close = self.buttons.addButton(tr("Close"),
                                       QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)


class TermsDialog(MarkdownDialog):
    """First-launch gate: the app opens only once the terms are accepted."""

    def __init__(self, parent=None, gate: bool = True):
        super().__init__(tr("Terms of use"), "terms", parent, 700, 600)
        if gate:
            ok = self.buttons.addButton(tr("I accept"),
                                        QDialogButtonBox.ButtonRole.AcceptRole)
            ok.setProperty("kind", "primary")
            no = self.buttons.addButton(tr("Decline and quit"),
                                        QDialogButtonBox.ButtonRole.RejectRole)
            ok.clicked.connect(self.accept)
            no.clicked.connect(self.reject)
        else:
            close = self.buttons.addButton(
                tr("Close"), QDialogButtonBox.ButtonRole.RejectRole)
            close.clicked.connect(self.reject)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("About ConvertCAD"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(64, 64))
        head.addWidget(logo)
        t = QVBoxLayout()
        t.addWidget(label(APP_NAME, "title"))
        t.addWidget(label(tr("Version {v}", v=APP_VERSION), "muted"))
        head.addSpacing(10)
        head.addLayout(t, 1)
        lay.addLayout(head)
        lay.addSpacing(6)
        lay.addWidget(label(tr("Converts 2D PDF drawings into editable DXF "
                               "files built with real CAD entities."),
                            wrap=True))
        lay.addWidget(label(tr("Everything runs on this computer. No drawing "
                               "ever leaves it."), "muted", wrap=True))
        lay.addWidget(label(tr("Created by {author}", author=APP_AUTHOR)
                            + f"  ©{APP_YEAR}"))
        import PySide6

        from ..core.compat import library_versions
        from ..core.dwg import dwg_status
        from ..core import ocr_store
        from ..core.licensing import license_summary
        from ..core.ocr_catalog import BY_ID
        versions = library_versions()
        versions["Qt / PySide6"] = PySide6.__version__
        if ocr_store.builtin_available():
            versions["RapidOCR (PP-OCR)"] = _module_version("rapidocr")
            versions["ONNX Runtime"] = _module_version("onnxruntime")
            versions[tr("OCR models")] = ", ".join(
                tr(BY_ID[i].label) for i in ocr_store.installed_ids())
        else:
            versions["RapidOCR (PP-OCR)"] = "—"
        dw = dwg_status()
        versions["GNU LibreDWG (DWG)"] = (dw["version"] or "✓") \
            if dw["available"] else "—"
        versions["Python"] = sys.version.split()[0]
        lay.addSpacing(6)
        lay.addWidget(label(tr("Components"), "faint"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        for i, (k, v) in enumerate(versions.items()):
            grid.addWidget(label(k, "muted"), i, 0)
            grid.addWidget(label(str(v)), i, 1)
        lay.addLayout(grid)
        lay.addWidget(label(tr(license_summary()), "caption"))
        box = QDialogButtonBox()
        close = box.addButton(tr("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        lay.addSpacing(8)
        lay.addWidget(box)


def _module_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:                                      # pragma: no cover
        return "✓"


class ShortcutsDialog(QDialog):
    ROWS = [
        ("Open PDF…", "Ctrl+O"), ("Convert", "Ctrl+Enter"),
        ("Save DXF…", "Ctrl+S"), ("Convert a folder…", "Ctrl+B"),
        ("Pan", "Esc"), ("Calibrate scale", "C"), ("Measure distance", "M"),
        ("Select area", "A"), ("Overlay the PDF on the DXF", "O"),
        ("Clear measurements", "Del"), ("Fit the sheet", "F"),
        ("Zoom in", "Ctrl++"), ("Zoom out", "Ctrl+-"),
        ("Zoom at the cursor", "Wheel"),
        ("Pan the view", "Middle button drag"),
        ("Pan the view", "Space + drag"),
        ("Next / previous sheet", "Page Down / Page Up"),
        ("Toggle object snap", "F3"),
        ("Source PDF", "Ctrl+1"), ("DXF result", "Ctrl+2"),
        ("User guide", "F1"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Keyboard shortcuts"))
        self.resize(460, 560)
        lay = QVBoxLayout(self)
        table = QTableWidget(len(self.ROWS), 2)
        table.setHorizontalHeaderLabels([tr("Action"), tr("Shortcut")])
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        for i, (a, k) in enumerate(self.ROWS):
            table.setItem(i, 0, QTableWidgetItem(tr(a)))
            keys = " / ".join(tr(x.strip()) for x in k.split("/"))
            table.setItem(i, 1, QTableWidgetItem(keys))
        table.resizeColumnToContents(0)
        lay.addWidget(table)
        box = QDialogButtonBox()
        close = box.addButton(tr("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        lay.addWidget(box)


class CalibrateDialog(QDialog):
    """Asks the real distance between two clicked points."""

    def __init__(self, length_pt: float, units: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Calibrate scale"))
        self.length_pt = max(length_pt, 1e-9)
        self.draw_units = units
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        lay.setSpacing(8)
        lay.addWidget(label(tr("Real distance between the two points")))
        row = QHBoxLayout()
        self.value = QDoubleSpinBox()
        self.value.setDecimals(3)
        self.value.setRange(0.0, 1e9)
        self.value.setMinimumWidth(150)
        self.value.setFocus()
        self.unit = QComboBox()
        for u in UNITS:
            self.unit.addItem(u, u)
        self.unit.setCurrentIndex(self.unit.findData(units))
        row.addWidget(self.value, 1)
        row.addWidget(self.unit)
        lay.addLayout(row)
        paper_mm = self.length_pt * PT_TO_MM
        lay.addWidget(label(tr("Measured on the sheet: {mm} mm of paper.",
                               mm=f"{paper_mm:.2f}"), "muted"))
        self.result = label("", "muted")
        lay.addWidget(self.result)
        box = QDialogButtonBox()
        self.ok = box.addButton(tr("Apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setProperty("kind", "primary")
        cancel = box.addButton(tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        lay.addWidget(box)
        self.value.valueChanged.connect(self._update)
        self.unit.currentIndexChanged.connect(self._update)
        self._update()

    def units_per_pt(self) -> float:
        """Real distance converted to DRAWING units, per page point."""
        mm = self.value.value() / UNITS[self.unit.currentData()]["factor"]
        return mm * UNITS[self.draw_units]["factor"] / self.length_pt

    def _update(self) -> None:
        v = self.value.value()
        self.ok.setEnabled(v > 0)
        if v > 0:
            mm = v / UNITS[self.unit.currentData()]["factor"]
            den = mm / (self.length_pt * PT_TO_MM)
            self.result.setText(tr("Resulting scale: about 1:{den}",
                                   den=f"{den:.4g}"))
        else:
            self.result.setText(tr("Enter a distance greater than zero."))


def open_folder(path: str) -> None:
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def open_file(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
