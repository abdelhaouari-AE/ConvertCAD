"""
pdf_view.py — the source-PDF viewer with CAD tools.

* The sheet is shown like paper on a drafting table (soft shadow).
* Rendering stays sharp at any zoom: a base image of the whole sheet plus a
  high-resolution "detail tile" of the visible area, re-rendered when the
  view settles.
* Tools: Pan, Measure distance, Calibrate scale — with object snap
  (endpoint, midpoint, intersection, centre) and AutoCAD-style glyphs —
  and Select area (drag a rectangle: only that part of the sheet is
  converted; the rest of the sheet is dimmed).
* Measurements are drawn as real dimension lines (oblique ticks + value).

Scene units are PAGE POINTS in displayed orientation (same as the engine).
"""

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem

from ..i18n import language, tr
from . import theme
from .cadview import CadView

MAX_BASE_PX = 3200          # longest side of the whole-sheet image
SNAP_PX = 12                # snap aperture in screen pixels

SNAP_NAMES = {"end": "Endpoint", "mid": "Midpoint", "int": "Intersection",
              "cen": "Center"}


# thousands and decimal separators of each interface language (French:
# narrow no-break space)
_SEPARATORS = {"fr": ("\u202f", ","), "es": (".", ","), "de": (".", ",")}


def format_length(value: float, unit: str) -> str:
    """'3,500.0 mm' (English, Arabic), '3 500,0 mm' (French), '3.500,0 mm'
    (Spanish, German); m with 3 decimals."""
    decimals = {"mm": 1, "cm": 2, "m": 3}.get(unit, 2)
    s = f"{value:,.{decimals}f}"
    thousands, decimal = _SEPARATORS.get(language(), (",", "."))
    s = s.replace(",", "\x00").replace(".", decimal)
    return f"{s.replace(chr(0), thousands)} {unit}"


class PdfView(CadView):
    cursor_moved = Signal(float, float)        # page coordinates (pt)
    cursor_left = Signal()
    tool_changed = Signal(str)
    calibration_picked = Signal(object, object)
    measurement_added = Signal(object, object)
    area_selected = Signal(object)              # QRectF (page points) or None
    hint = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, flip_y=False)
        self.doc = None
        self.page_index = -1
        self.page_rect = QRectF()
        self._base_item: Optional[QGraphicsPixmapItem] = None
        self._base_zoom = 1.0
        self._tile_item: Optional[QGraphicsPixmapItem] = None
        self._shadow: Optional[QGraphicsRectItem] = None
        self.tool = "pan"
        self.snap_enabled = True
        self.snap_modes = {"end", "mid", "int", "cen"}
        self._snap_cache: Dict[int, "SnapEngine"] = {}  # noqa: F821
        self._picks: List[QPointF] = []
        self._hover: Optional[QPointF] = None
        self._hover_hit = None                      # snap.SnapHit
        self._mouse: Optional[QPointF] = None
        self.measurements: List[Tuple[QPointF, QPointF]] = []
        self.calibration: Optional[Tuple[QPointF, QPointF, str]] = None
        self.area: Optional[QRectF] = None          # selected area (page pt)
        self._drag_start: Optional[QPointF] = None  # area being drawn
        self.units_per_pt = 25.4 / 72.0 * 50
        self.unit = "mm"
        self.setViewportUpdateMode(
            CadView.ViewportUpdateMode.FullViewportUpdate)
        self.view_changed.connect(self._update_tile)
        self.restore_cursor()

    # ---- document & page --------------------------------------------------------
    def set_document(self, doc) -> None:
        self.doc = doc
        self.page_index = -1
        self.area = None
        self._drag_start = None
        self._snap_cache.clear()
        self.measurements.clear()
        self.calibration = None
        self._picks.clear()
        self.scene().clear()
        self._base_item = self._tile_item = self._shadow = None

    def show_page(self, index: int, fit: bool = True) -> None:
        if self.doc is None or not 0 <= index < self.doc.page_count:
            return
        changed = index != self.page_index
        self.page_index = index
        page = self.doc[index]
        r = page.rect
        self.page_rect = QRectF(0, 0, r.width, r.height)
        self.scene().clear()
        self._tile_item = None
        if changed:
            self.measurements.clear()
            self._picks.clear()
        shadow_off = max(r.width, r.height) * 0.006
        self._shadow = self.scene().addRect(
            self.page_rect.translated(shadow_off, shadow_off),
            QPen(Qt.PenStyle.NoPen), QBrush(theme.qcolor("sheet_shadow")))
        self._shadow.setZValue(-2)
        self._base_zoom = min(MAX_BASE_PX / max(r.width, r.height, 1), 4.0)
        img = self._render(page, self._base_zoom, None)
        self._base_item = self.scene().addPixmap(QPixmap.fromImage(img))
        self._base_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        self._base_item.setScale(1.0 / self._base_zoom)
        self._base_item.setZValue(-1)
        if fit or changed:
            self.fit()
        self.viewport().update()

    def content_rect(self) -> QRectF:
        return QRectF(self.page_rect)

    @staticmethod
    def _render(page, zoom: float, clip) -> QImage:
        from ..core.compat import pymupdf
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip,
                              alpha=False)
        fmt = QImage.Format.Format_RGB888 if pix.n == 3 \
            else QImage.Format.Format_Grayscale8
        return QImage(pix.samples, pix.width, pix.height, pix.stride,
                      fmt).copy()

    def _update_tile(self) -> None:
        """Re-render the visible area at screen resolution when zoomed in."""
        if self.doc is None or self.page_index < 0:
            return
        dpr = self.devicePixelRatioF()
        need = self.current_scale() * dpr
        if need <= self._base_zoom * 1.05:
            if self._tile_item is not None:
                self.scene().removeItem(self._tile_item)
                self._tile_item = None
            return
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        vis = vis.intersected(self.page_rect)
        if vis.isEmpty():
            return
        if vis.width() * vis.height() * need * need > 40_000_000:
            return                                       # safety cap
        from ..core.compat import pymupdf
        page = self.doc[self.page_index]
        clip = pymupdf.Rect(vis.left(), vis.top(), vis.right(), vis.bottom())
        try:
            img = self._render(page, need, clip)
        except Exception:                                  # pragma: no cover
            return
        if self._tile_item is not None:
            self.scene().removeItem(self._tile_item)
        self._tile_item = self.scene().addPixmap(QPixmap.fromImage(img))
        self._tile_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        self._tile_item.setScale(1.0 / need)
        self._tile_item.setPos(vis.topLeft())
        self._tile_item.setZValue(0)

    def apply_colors(self) -> None:
        super().apply_colors()
        if getattr(self, "_shadow", None) is not None:
            self._shadow.setBrush(QBrush(theme.qcolor("sheet_shadow")))

    # ---- scale used for labels ------------------------------------------------------
    def set_scale_info(self, units_per_pt: float, unit: str) -> None:
        self.units_per_pt = units_per_pt
        self.unit = unit
        self.viewport().update()

    def real_length(self, a: QPointF, b: QPointF) -> float:
        return math.hypot(b.x() - a.x(), b.y() - a.y()) * self.units_per_pt

    # ---- tools ------------------------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._picks.clear()
        self.restore_cursor()
        self.tool_changed.emit(tool)
        if tool == "calibrate":
            self.hint.emit(tr("Calibration: click the first point."))
        elif tool == "measure":
            self.hint.emit(tr("Measure: click the first point."))
        elif tool == "area":
            self.hint.emit(tr("Select area: drag a rectangle around the part "
                              "to convert."))
        self._drag_start = None
        self.viewport().update()

    def is_pan_tool(self) -> bool:
        return self.tool == "pan"

    def restore_cursor(self) -> None:
        if self.tool == "pan":
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def clear_measurements(self) -> None:
        self.measurements.clear()
        self._picks.clear()
        self.viewport().update()

    def set_area(self, rect: Optional[QRectF]) -> None:
        """Show (or clear) the selected area."""
        self.area = QRectF(rect) if rect is not None else None
        self.viewport().update()

    def set_calibration_overlay(self, p1, p2, text: str) -> None:
        self.calibration = (p1, p2, text) if p1 is not None else None
        self.viewport().update()

    def snap_engine(self):
        if self.doc is None or self.page_index < 0:
            return None
        from .snap import SnapEngine                 # NumPy: loaded on use
        eng = self._snap_cache.get(self.page_index)
        if eng is None:
            self.viewport().setCursor(Qt.CursorShape.WaitCursor)
            try:
                eng = SnapEngine.from_page(self.doc[self.page_index])
            finally:
                self.restore_cursor()
            self._snap_cache[self.page_index] = eng
        return eng

    def _snapped(self, scene_pt: QPointF):
        if not (self.snap_enabled and self.snap_modes):
            return scene_pt, None
        eng = self.snap_engine()
        if eng is None:
            return scene_pt, None
        tol = SNAP_PX / max(self.current_scale(), 1e-9)
        hit = eng.query(scene_pt.x(), scene_pt.y(), tol, self.snap_modes)
        if hit is None:
            return scene_pt, None
        return QPointF(*hit.point), hit

    # ---- mouse ------------------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._panning or self.doc is None:
            return
        self._mouse = QPointF(event.position())
        sp = self.mapToScene(event.position().toPoint())
        if self.tool in ("measure", "calibrate", "area") and not self._space:
            sp, hit = self._snapped(sp)
            self._hover, self._hover_hit = sp, hit
        else:
            self._hover, self._hover_hit = sp, None
        self.cursor_moved.emit(sp.x(), sp.y())
        self.viewport().update()

    def leaveEvent(self, event) -> None:
        self._hover = self._mouse = None
        self._hover_hit = None
        self.cursor_left.emit()
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.tool == "area" and not self._space
                and self.doc is not None):
            sp, _ = self._snapped(self.mapToScene(event.position().toPoint()))
            self._drag_start = sp
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton
                and self.tool in ("measure", "calibrate") and not self._space
                and self.doc is not None):
            sp = self.mapToScene(event.position().toPoint())
            sp, _ = self._snapped(sp)
            self._picks.append(sp)
            if len(self._picks) == 1:
                self.hint.emit(tr("Calibration: click the second point.")
                               if self.tool == "calibrate"
                               else tr("Measure: click the second point."))
            else:
                a, b = self._picks
                self._picks.clear()
                if self.tool == "measure":
                    self.measurements.append((a, b))
                    self.measurement_added.emit(a, b)
                    self.hint.emit(tr("Measure: click the first point."))
                else:
                    self.calibration_picked.emit(a, b)
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self._picks:
            self._picks.clear()                    # right click cancels
            self.viewport().update()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.tool == "area" and self._drag_start is not None):
            sp, _ = self._snapped(self.mapToScene(event.position().toPoint()))
            rect = QRectF(self._drag_start, sp).normalized()
            rect = rect.intersected(self.page_rect)
            self._drag_start = None
            if rect.width() * self.current_scale() >= 6 and \
                    rect.height() * self.current_scale() >= 6:
                self.area = rect
                self.area_selected.emit(QRectF(rect))
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._drag_start is not None:
                self._drag_start = None
                self.viewport().update()
                return
            if self._picks:
                self._picks.clear()
                self.viewport().update()
            else:
                self.set_tool("pan")
            return
        super().keyPressEvent(event)

    # ---- overlays ------------------------------------------------------------------------
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self.doc is None:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        vt = self.viewportTransform()
        area = self.area
        if self._drag_start is not None and self._hover is not None:
            area = QRectF(self._drag_start, self._hover).normalized()
        if area is not None:
            self._draw_area(painter, vt.mapRect(area),
                            vt.mapRect(self.page_rect),
                            live=self._drag_start is not None)
        if self.calibration is not None:
            a, b, text = self.calibration
            self._draw_dim(painter, vt.map(a), vt.map(b), text,
                           QColor(theme.MARKUP["calibrate"]))
        mcol = QColor(theme.MARKUP["measure"])
        for a, b in self.measurements:
            self._draw_dim(painter, vt.map(a), vt.map(b),
                           format_length(self.real_length(a, b), self.unit),
                           mcol)
        tool_col = QColor(theme.MARKUP["calibrate" if self.tool == "calibrate"
                                       else "measure"])
        if self._picks and self._hover is not None:
            a, b = self._picks[0], self._hover
            self._draw_dim(painter, vt.map(a), vt.map(b),
                           format_length(self.real_length(a, b), self.unit),
                           tool_col, preview=True)
        for p in self._picks:
            self._draw_point(painter, vt.map(p), tool_col)
        if self.tool != "pan" and self._mouse is not None and not self._panning:
            self._draw_crosshair(painter, self._mouse)
            if self._hover_hit is not None:
                self._draw_snap(painter, vt.map(self._hover), self._hover_hit.kind)
        painter.restore()

    def _draw_area(self, p: QPainter, r: QRectF, sheet: QRectF,
                   live: bool) -> None:
        """Selected area: the rest of the sheet is dimmed, the area framed."""
        dim = QColor(0, 0, 0, 70 if theme.current() == "light" else 110)
        path = QPainterPath()
        path.addRect(sheet)
        inner = QPainterPath()
        inner.addRect(r)
        p.fillPath(path.subtracted(inner), dim)
        col = QColor(theme.MARKUP["area"])
        pen = QPen(col, 1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if not live:
            w_txt = format_length(r.width() / max(self.current_scale(), 1e-9)
                                  * self.units_per_pt, self.unit)
            h_txt = format_length(r.height() / max(self.current_scale(), 1e-9)
                                  * self.units_per_pt, self.unit)
            self._label(p, QPointF(r.left() + 6, r.top() - 12),
                        f"{tr('Area')}  {w_txt} × {h_txt}", col, small=True,
                        align_left=True)

    def _draw_crosshair(self, p: QPainter, c: QPointF) -> None:
        col = QColor(theme.tok("text")) if theme.current() == "dark" \
            else QColor("#1B232B")
        pen = QPen(col, 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        arm, box = 22, 5
        p.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() - box, c.y()))
        p.drawLine(QPointF(c.x() + box, c.y()), QPointF(c.x() + arm, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() - box))
        p.drawLine(QPointF(c.x(), c.y() + box), QPointF(c.x(), c.y() + arm))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(c.x() - box, c.y() - box, 2 * box, 2 * box))

    def _draw_snap(self, p: QPainter, c: QPointF, kind: str) -> None:
        col = QColor(theme.MARKUP["snap"])
        pen = QPen(col, 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        s = 6.5
        if kind == "end":
            p.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
        elif kind == "mid":
            path = QPainterPath(QPointF(c.x(), c.y() - s - 1))
            path.lineTo(c.x() + s + 1, c.y() + s)
            path.lineTo(c.x() - s - 1, c.y() + s)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "int":
            p.drawLine(QPointF(c.x() - s, c.y() - s), QPointF(c.x() + s, c.y() + s))
            p.drawLine(QPointF(c.x() - s, c.y() + s), QPointF(c.x() + s, c.y() - s))
        else:
            p.drawEllipse(c, s, s)
        self._label(p, QPointF(c.x() + 14, c.y() + 18), tr(SNAP_NAMES[kind]),
                    col, small=True, align_left=True)

    def _draw_point(self, p: QPainter, c: QPointF, col: QColor) -> None:
        p.setPen(QPen(col, 1.6))
        p.setBrush(QBrush(QColor(theme.MARKUP["halo"])))
        p.drawEllipse(c, 3.2, 3.2)

    def _label(self, p: QPainter, at: QPointF, text: str, col: QColor,
               small: bool = False, align_left: bool = False,
               angle: float = 0.0) -> None:
        f = QFont(theme.ui_font(8.0 if small else 9.0, QFont.Weight.DemiBold))
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 10
        h = fm.height() + 4
        p.save()
        p.translate(at)
        p.rotate(angle)
        box = QRectF(0 if align_left else -w / 2, -h / 2, w, h)
        halo = QColor(theme.MARKUP["halo"])
        halo.setAlpha(225)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawRoundedRect(box, 3, 3)
        p.setPen(col)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _draw_dim(self, p: QPainter, a: QPointF, b: QPointF, text: str,
                  col: QColor, preview: bool = False) -> None:
        """A measurement drawn like a drafting dimension (oblique ticks)."""
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L = math.hypot(dx, dy)
        pen = QPen(col, 1.6)
        if preview:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(a, b)
        if L < 1:
            return
        ux, uy = dx / L, dy / L
        tx, ty = (ux - uy) / math.sqrt(2), (uy + ux) / math.sqrt(2)
        p.setPen(QPen(col, 2))
        for c in (a, b):
            p.drawLine(QPointF(c.x() - tx * 6, c.y() - ty * 6),
                       QPointF(c.x() + tx * 6, c.y() + ty * 6))
        angle = math.degrees(math.atan2(dy, dx))
        if angle > 90:
            angle -= 180
        elif angle <= -90:
            angle += 180
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        nx, ny = -math.sin(math.radians(angle)), math.cos(math.radians(angle))
        at = QPointF(mid.x() - nx * 13, mid.y() - ny * 13)
        self._label(p, at, text, col, angle=angle)
