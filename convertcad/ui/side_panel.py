"""
side_panel.py — side panels that collapse to a thin bar, like AutoCAD palettes.

The Sheets panel (left) and the Settings / Layers / Report panel (right) are
each wrapped in a SidePanel: a narrow vertical bar on the outer edge of the
window holds a chevron and the panel's name written vertically. Clicking the
bar (or View > Sheets panel / Settings panel) collapses the panel to that bar
and gives the drawing all the room; clicking again opens it at its previous
width.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from ..i18n import tr
from . import theme

STRIP_WIDTH = 22                 # px, the bar left when collapsed


class _Strip(QWidget):
    """The vertical bar: chevron at the top, the panel name below it."""
    clicked = Signal()

    def __init__(self, title: str, side: str, parent=None):
        super().__init__(parent)
        self.title, self.side = title, side
        self.collapsed = False
        self._hover = False
        self.setFixedWidth(STRIP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self._update_tip()

    def _update_tip(self) -> None:
        self.setToolTip(tr("Open the {name} panel", name=self.title)
                        if self.collapsed else
                        tr("Collapse the {name} panel", name=self.title))

    def set_collapsed(self, on: bool) -> None:
        self.collapsed = on
        self._update_tip()
        self.update()

    def sizeHint(self) -> QSize:                     # noqa: N802 (Qt name)
        return QSize(STRIP_WIDTH, 100)

    def enterEvent(self, event) -> None:             # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:             # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:      # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event) -> None:             # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = theme.qcolor("panel_alt" if self._hover else "panel")
        p.fillRect(self.rect(), bg)
        # border towards the drawing
        p.setPen(QPen(theme.qcolor("border"), 1))
        x = self.width() - 1 if self.side == "left" else 0
        p.drawLine(x, 0, x, self.height())
        # chevron: points to where the panel will go
        w = self.width()
        cx, cy, a = w / 2, 16, 4
        opening = self.collapsed
        towards_right = (self.side == "left") == opening
        path = QPainterPath()
        if towards_right:
            path.moveTo(cx - a / 2, cy - a)
            path.lineTo(cx + a / 2, cy)
            path.lineTo(cx - a / 2, cy + a)
        else:
            path.moveTo(cx + a / 2, cy - a)
            path.lineTo(cx - a / 2, cy)
            path.lineTo(cx + a / 2, cy + a)
        color = theme.qcolor("text" if self._hover else "text_muted")
        p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        # panel name, written vertically (bottom to top on the left,
        # top to bottom on the right, like AutoCAD palette title bars)
        f = theme.ui_font(9.0, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.save()
        if self.side == "left":
            p.translate(0, self.height())
            p.rotate(-90)
            box = QRectF(0, 0, self.height() - 32, w)
            p.drawText(box, Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, self.title)
        else:
            p.translate(w, 0)
            p.rotate(90)
            box = QRectF(32, 0, self.height() - 32, w)
            p.drawText(box, Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, self.title)
        p.restore()


class SidePanel(QWidget):
    """A panel with its collapse bar on the outer edge of the window."""
    collapsed_changed = Signal(bool)

    def __init__(self, content: QWidget, title: str, side: str, parent=None):
        super().__init__(parent)
        self.content = content
        self.side = side
        self.collapsed = False
        self.strip = _Strip(title, side, self)
        self.strip.clicked.connect(self.toggle)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # the bar on the window edge: left of the Sheets panel, right of
        # the Settings panel (mirrored automatically in Arabic)
        if side == "left":
            lay.addWidget(self.strip)
            lay.addWidget(content, 1)
        else:
            lay.addWidget(content, 1)
            lay.addWidget(self.strip)
        self._content_min = content.minimumWidth()

    def toggle(self) -> None:
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, on: bool) -> None:
        if on == self.collapsed:
            return
        self.collapsed = on
        self.content.setVisible(not on)
        if on:
            self.setFixedWidth(STRIP_WIDTH)
        else:
            self.setMinimumWidth(STRIP_WIDTH + self._content_min)
            self.setMaximumWidth(16777215)
        self.strip.set_collapsed(on)
        self.collapsed_changed.emit(on)

    def refresh_theme(self) -> None:
        self.strip.update()
