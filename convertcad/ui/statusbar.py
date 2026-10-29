"""
statusbar.py — the status bar, built like a drawing's title block.

Ruled cells, each with a small caption and a value — the layout every
engineer reads at a glance on a drawing sheet:

| Sheet | Paper | Scale | Cursor X / Y | Snap END MID INT CEN | Zoom | status |
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr


class _Cell(QFrame):
    def __init__(self, caption: str, value: str = "", min_w: int = 0,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("TBCell")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 3, 12, 4)
        lay.setSpacing(0)
        self.caption = QLabel(caption)
        self.caption.setObjectName("TBCaption")
        self.value = QLabel(value)
        self.value.setObjectName("TBValue")
        self.value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.caption)
        lay.addWidget(self.value)
        if min_w:
            self.setMinimumWidth(min_w)

    def set(self, text: str) -> None:
        self.value.setText(text)


class TitleBlockBar(QFrame):
    snap_toggled = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBlock")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(0)
        self.sheet = _Cell(tr("Sheet"), "–", 70)
        self.paper = _Cell(tr("Paper"), "–", 120)
        self.scale = _Cell(tr("Scale"), "–", 120)
        self.cursor = _Cell(tr("Cursor"), "–", 210)
        for c in (self.sheet, self.paper, self.scale, self.cursor):
            lay.addWidget(c)
        snap = QFrame()
        snap.setObjectName("TBCell")
        sl = QVBoxLayout(snap)
        sl.setContentsMargins(10, 3, 12, 4)
        sl.setSpacing(1)
        cap = QLabel(tr("Snap"))
        cap.setObjectName("TBCaption")
        sl.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.snap_buttons = {}
        for key, text, tip in (("end", tr("END"), tr("Snap to endpoints")),
                               ("mid", tr("MID"), tr("Snap to midpoints")),
                               ("int", tr("INT"), tr("Snap to intersections")),
                               ("cen", tr("CEN"), tr("Snap to circle centres"))):
            b = QToolButton()
            b.setObjectName("SnapToggle")
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(True)
            b.toggled.connect(lambda on, k=key: self.snap_toggled.emit(k, on))
            row.addWidget(b)
            self.snap_buttons[key] = b
        sl.addLayout(row)
        lay.addWidget(snap)
        self.zoom = _Cell(tr("Zoom"), "–", 64)
        lay.addWidget(self.zoom)
        right = QWidget()
        rl = QHBoxLayout(right)
        rl.setContentsMargins(12, 0, 4, 0)
        rl.setSpacing(10)
        self.message = QLabel(tr("Ready"))
        self.message.setObjectName("TBValue")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(160)
        self.progress.setTextVisible(False)
        self.progress.hide()
        rl.addWidget(self.message, 1)
        rl.addWidget(self.progress)
        lay.addWidget(right, 1)

    def set_snaps(self, modes: dict) -> None:
        for k, b in self.snap_buttons.items():
            b.blockSignals(True)
            b.setChecked(bool(modes.get(k, True)))
            b.blockSignals(False)

    def set_progress(self, frac) -> None:
        """0..1 = progress; a negative value = busy (moving bar);
        None = hidden."""
        if frac is None:
            self.progress.hide()
            self.progress.setRange(0, 1000)
            return
        self.progress.show()
        if frac < 0:
            self.progress.setRange(0, 0)                  # busy indicator
            return
        self.progress.setRange(0, 1000)
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))
