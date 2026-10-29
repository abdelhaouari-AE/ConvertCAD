"""
report_panel.py — the conversion report (and the activity log).

ReportPanel   styled summary of the last conversion: results, layers,
              warnings, errors, options. Export as .txt or .html, or copy.
ActivityPanel running log of what the application did (timestamps).
"""

import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout,
                               QPlainTextEdit, QPushButton, QStackedWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..core.report import ConversionReport
from ..i18n import tr
from . import theme
from .icons import icon
from .widgets import PanelHeader, label, small_button


class ReportPanel(QFrame):
    message = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.settings = settings
        self.report: Optional[ConversionReport] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        empty = label(tr("Convert a drawing to see its report here."),
                      "muted", wrap=True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(empty)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(10, 8, 6, 8)
        pl.setSpacing(6)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        pl.addWidget(self.browser, 1)
        row = QHBoxLayout()
        row.setSpacing(4)
        # short labels + tooltips: the panel is narrow and must fit French too
        self.btn_txt = QPushButton(icon("export"), tr("Save log…"))
        self.btn_txt.setToolTip(tr("Save the log as a text file"))
        self.btn_txt.clicked.connect(self.save_txt)
        self.btn_html = QPushButton(icon("report"), tr("Save HTML…"))
        self.btn_html.setToolTip(tr("Save the report as an HTML page"))
        self.btn_html.clicked.connect(self.save_html)
        self.btn_copy = QPushButton(icon("copy"), tr("Copy"))
        self.btn_copy.setToolTip(tr("Copy the log to the clipboard"))
        self.btn_copy.clicked.connect(self.copy)
        for b, name in ((self.btn_txt, "export"), (self.btn_html, "report"),
                        (self.btn_copy, "copy")):
            b.setProperty("iconName", name)       # recoloured on theme change
            row.addWidget(b)
        row.addStretch(1)
        pl.addLayout(row)
        self.stack.addWidget(page)
        lay.addWidget(self.stack)

    def show_report(self, rep: Optional[ConversionReport]) -> None:
        self.report = rep
        if rep is None:
            self.stack.setCurrentIndex(0)
            return
        self.browser.setHtml(rep.to_html(dark=theme.current() == "dark", t=tr))
        self.stack.setCurrentIndex(1)

    def refresh(self) -> None:
        self.show_report(self.report)

    def _ask(self, filt: str, suffix: str) -> str:
        base = (self.report.dxf_path or self.report.pdf_path or "report")
        import os
        start = os.path.splitext(base)[0] + suffix
        path, _ = QFileDialog.getSaveFileName(self, tr("Save the report…"),
                                              start, filt)
        return path

    def save_txt(self) -> None:
        if not self.report:
            return
        path = self._ask(tr("Text file (*.txt)"), "_log.txt")
        if path:
            self.report.save(path)
            self.message.emit(tr("Saved {name}.", name=path))

    def save_html(self) -> None:
        if not self.report:
            return
        path = self._ask(tr("HTML page (*.html)"), "_report.html")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.report.to_html(dark=False, t=tr))
            self.message.emit(tr("Saved {name}.", name=path))

    def copy(self) -> None:
        if self.report:
            QGuiApplication.clipboard().setText(self.report.render())
            self.message.emit(tr("Copied to the clipboard."))


class ActivityPanel(QFrame):
    """Timestamped log of the session (opening, converting, saving)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        clear_btn = small_button("clear", tr("Clear"))
        self.header = PanelHeader(tr("Activity"), [clear_btn])
        lay.addWidget(self.header)
        self.text = QPlainTextEdit()
        self.text.setObjectName("Activity")
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font(8.5))
        self.text.setMaximumBlockCount(5000)
        clear_btn.clicked.connect(self.text.clear)
        lay.addWidget(self.text)
        self._last = ""

    def log(self, msg: str) -> None:
        if msg == self._last:
            return
        self._last = msg
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.text.appendPlainText(f"{ts}  {msg}")
