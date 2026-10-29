"""
empty_state.py — what the window shows before a drawing is opened.

An invitation to act: drop a PDF or open one, try the sample plan, or pick
a recent drawing — with the four steps of the workflow, in order.
"""

import os
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..i18n import tr
from . import theme
from .icons import icon, icon_size
from .widgets import label, restyle


class EmptyState(QWidget):
    open_requested = Signal()
    sample_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("DropCard")
        self.card.setMaximumWidth(620)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(36, 32, 36, 30)
        cl.setSpacing(10)
        pic = QLabel()
        pic.setPixmap(icon("drop", theme.tok("accent")).pixmap(56, 56))
        cl.addWidget(pic, 0, Qt.AlignmentFlag.AlignHCenter)
        title = label(tr("Drop a PDF drawing here"), "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)
        sub = label(tr("Vector PDFs exported from CAD give the best result. "
                       "Scanned drawings are traced and read with OCR."),
                    "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(sub)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_open = QPushButton(icon("open", theme.tok("on_accent")),
                             tr("Open PDF…"))
        b_open.setProperty("kind", "primary")
        b_open.setIconSize(icon_size(16))
        b_open.clicked.connect(self.open_requested.emit)
        b_sample = QPushButton(icon("sample"), tr("Try the sample plan"))
        b_sample.clicked.connect(self.sample_requested.emit)
        btns.addWidget(b_open)
        btns.addWidget(b_sample)
        btns.addStretch(1)
        cl.addSpacing(6)
        cl.addLayout(btns)
        cl.addSpacing(14)
        steps = QHBoxLayout()
        steps.setSpacing(14)
        for n, text in enumerate((tr("Open a drawing"), tr("Check the scale"),
                                  tr("Convert"), tr("Review and save")), 1):
            s = QHBoxLayout()
            s.setSpacing(6)
            num = QLabel(str(n))
            num.setObjectName("StepNumber")
            s.addWidget(num)
            s.addWidget(label(text, "muted"))
            steps.addLayout(s)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addLayout(steps)
        wrap.addStretch(1)
        cl.addLayout(wrap)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        cl.addSpacing(8)
        cl.addLayout(self.recent_box)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.setAcceptDrops(False)       # the main window handles drops

    def set_recent(self, paths: List[str]) -> None:
        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not paths:
            return
        self.recent_box.addWidget(label(tr("Recent drawings"), "faint"))
        for p in paths[:5]:
            b = QPushButton(os.path.basename(p))
            b.setProperty("kind", "link")
            b.setToolTip(p)
            b.clicked.connect(lambda _=False, path=p:
                              self.recent_requested.emit(path))
            self.recent_box.addWidget(b)

    def set_drag_active(self, on: bool) -> None:
        self.card.setProperty("drag", "true" if on else "false")
        restyle(self.card)
