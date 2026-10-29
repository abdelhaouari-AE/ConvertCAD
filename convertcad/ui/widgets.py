"""
widgets.py — small reusable interface pieces.

PanelHeader        title strip at the top of a side panel
CollapsibleSection settings group that opens/closes (chevron)
Toast              short message fading out over a view
hline / label      tiny helpers for consistent layouts
"""

from typing import Iterable, Optional

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                            Signal)
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from . import theme
from .icons import icon, icon_size


def label(text: str = "", role: str = "", wrap: bool = False,
          parent: Optional[QWidget] = None) -> QLabel:
    lb = QLabel(text, parent)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{theme.tok('border')}; border:0;")
    return f


def restyle(w: QWidget) -> None:
    """Re-apply the style sheet after changing a dynamic property."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class PanelHeader(QFrame):
    """Panel title with optional small action buttons on the right."""

    def __init__(self, title: str, actions: Iterable[QWidget] = (),
                 parent=None):
        super().__init__(parent)
        self.setObjectName("PanelHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 6, 7)
        lay.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("PanelTitle")
        lay.addWidget(self.title)
        lay.addStretch(1)
        for a in actions:
            lay.addWidget(a)


def small_button(icon_name: str, tooltip: str, parent=None,
                 checkable: bool = False) -> QToolButton:
    b = QToolButton(parent)
    b.setIcon(icon(icon_name, theme.tok("text_muted")))
    b.setIconSize(icon_size(16))
    b.setToolTip(tooltip)
    b.setAutoRaise(True)
    b.setCheckable(checkable)
    b.setProperty("iconName", icon_name)
    return b


class CollapsibleSection(QWidget):
    """A settings group: a header button that shows/hides its content."""

    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        self.header.setIconSize(icon_size(14))
        self.header.clicked.connect(self._on_click)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 2, 4, 10)
        self.body_layout.setSpacing(5)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self._apply(expanded)

    def _on_click(self) -> None:
        self._apply(self.header.isChecked())
        self.toggled.emit(self.header.isChecked())

    def _apply(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setIcon(icon("chevron_down" if expanded else
                                 "chevron_right", theme.tok("text_muted")))

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self._apply(expanded)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def add(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def refresh_icons(self) -> None:
        self._apply(self.header.isChecked())


class Toast(QLabel):
    """Message bubble shown over a widget for a few seconds."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.hide()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_message(self, text: str, level: str = "info",
                     ms: int = 4500) -> None:
        self.setText(text)
        self.setProperty("level", level)
        restyle(self)
        self.adjustSize()
        self._place()
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def _place(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        x = (p.width() - self.width()) // 2
        y = p.height() - self.height() - 24
        self.move(max(8, x), max(8, y))

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        try:
            self._anim.finished.disconnect(self._hide_once)
        except (RuntimeError, TypeError):
            pass
        if self._effect.opacity() < 0.05:
            self.hide()
