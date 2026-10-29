"""
cadview.py — common behaviour of the two drawing views (PDF and DXF).

CAD-style navigation:
  * mouse wheel           zoom in/out at the cursor
  * middle-button drag    pan (always)
  * left drag             pan in the Pan tool
  * Space + left drag     temporary pan in any tool
  * F / Fit button        fit the drawing
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from . import theme

ZOOM_STEP = 1.2


class CadView(QGraphicsView):
    zoom_changed = Signal(float)          # current scale (view px per unit)
    view_changed = Signal()               # pan/zoom settled (debounced)

    def __init__(self, parent=None, flip_y: bool = False):
        super().__init__(parent)
        self.flip_y = flip_y
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._panning = False
        self._pan_start = QPointF()
        self._space = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(140)
        self._settle.timeout.connect(self.view_changed.emit)
        self.horizontalScrollBar().valueChanged.connect(self._kick)
        self.verticalScrollBar().valueChanged.connect(self._kick)
        self.apply_colors()

    # ---- appearance -------------------------------------------------------
    def background_token(self) -> str:
        return "canvas"

    def apply_colors(self) -> None:
        self.setBackgroundBrush(theme.qcolor(self.background_token()))

    # ---- zoom -----------------------------------------------------------------
    def current_scale(self) -> float:
        return abs(self.transform().m11())

    def _kick(self) -> None:
        self._settle.start()

    def set_scale(self, s: float, anchor: QPointF = None) -> None:
        s = max(1e-6, min(s, 1e6))
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        scene_pt = self.mapToScene(anchor.toPoint())
        t = QTransform.fromScale(s, -s if self.flip_y else s)
        self.setTransform(t)
        # keep the scene point under the anchor
        new_pos = self.mapFromScene(scene_pt)
        delta = new_pos - anchor.toPoint()
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + delta.y())
        self.zoom_changed.emit(s)
        self._kick()

    def zoom_by(self, factor: float, anchor: QPointF = None) -> None:
        lo, hi = self.zoom_limits()
        s = max(lo, min(hi, self.current_scale() * factor))
        if abs(s - self.current_scale()) > 1e-12:
            self.set_scale(s, anchor)

    def zoom_limits(self):
        fit = self.fit_scale() or 1.0
        return fit * 0.2, fit * 400.0

    def content_rect(self) -> QRectF:
        return self.scene().itemsBoundingRect()

    def fit_scale(self) -> float:
        r = self.content_rect()
        if r.isEmpty():
            return 0.0
        vw = max(self.viewport().width() - 40, 50)
        vh = max(self.viewport().height() - 40, 50)
        return min(vw / r.width(), vh / r.height())

    def fit(self) -> None:
        r = self.content_rect()
        if r.isEmpty():
            return
        margin = max(r.width(), r.height()) * 0.5
        self.setSceneRect(r.adjusted(-margin, -margin, margin, margin))
        s = self.fit_scale()
        self.setTransform(QTransform.fromScale(s, -s if self.flip_y else s))
        self.centerOn(r.center())
        self.zoom_changed.emit(s)
        self._kick()

    # ---- events -------------------------------------------------------------
    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return
        factor = ZOOM_STEP ** (delta / 120.0)
        self.zoom_by(factor, event.position())
        event.accept()

    def is_pan_tool(self) -> bool:
        return True

    def _start_pan(self, pos) -> None:
        self._panning = True
        self._pan_start = QPointF(pos)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton
                and (self._space or self.is_pan_tool())):
            self._start_pan(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            d = event.position() - self._pan_start
            self._pan_start = QPointF(event.position())
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - d.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton,
                                                Qt.MouseButton.LeftButton):
            self._panning = False
            self.restore_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.restore_cursor()
            return
        super().keyReleaseEvent(event)

    def restore_cursor(self) -> None:
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor
                                  if self.is_pan_tool()
                                  else Qt.CursorShape.CrossCursor)
