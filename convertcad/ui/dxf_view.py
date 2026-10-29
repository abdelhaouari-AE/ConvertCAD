"""
dxf_view.py — preview of the converted DXF, inside the application.

The DXF is interpreted by ezdxf's own drawing engine, so what you see is the
CAD reading of the file (layers, linetypes, blocks, dimensions, leaders,
hatch patterns) — not a re-drawing of the PDF.

Speed (a sheet can hold 50 000+ entities):
  * the heavy work — reading the DXF, exploding blocks, dimensions and text
    into primitives — runs in a background thread (ezdxf Recorder);
  * the primitives are then MERGED: one Qt path item per layer, colour, line
    weight and screen tile instead of one item per primitive. A sheet that
    used to create 60 000 scene items now creates a few hundred, so opening,
    panning and zooming stay fluid.

Visibility: lines are drawn with "cosmetic" pens (a fixed width in screen
pixels), so a hairline of the PDF never disappears when zoomed out.

Overlay check: the PDF sheet can be shown under the DXF (semi-transparent,
at the exact place and scale of the conversion) to compare both at a glance.

Each item remembers the layer(s) it belongs to, so switching a layer off in
the Layers panel hides it instantly.
"""

import os
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsPixmapItem

from ..i18n import tr
from . import theme
from .cadview import CadView

LAYERS_ROLE = int(Qt.ItemDataRole.UserRole) + 40
TILES = 8                                   # screen tiles per side (culling)


def _make_recorder_class():
    """Recorder that also records which layers each primitive belongs to
    (its own layer + the layers of the INSERTs it is nested in)."""
    from ezdxf.addons.drawing.recorder import Recorder

    class LayerRecorder(Recorder):
        def __init__(self):
            super().__init__()
            self._stack: List[str] = []

        def enter_entity(self, entity, properties) -> None:
            try:
                self._stack.append(entity.dxf.layer.upper())
            except Exception:
                self._stack.append("")

        def exit_entity(self, entity) -> None:
            if self._stack:
                self._stack.pop()

        def store(self, record, properties) -> None:
            super().store(record, properties)
            layers = {n for n in self._stack[:-1] if n and n != "0"}
            layers.add((properties.layer or "0").upper())
            record.vis_layers = frozenset(layers)

    return LayerRecorder


def _pen_width(lineweight_mm: float) -> float:
    """Screen width (pixels) of a line: thin, medium or heavy."""
    if lineweight_mm >= 0.70:
        return 2.2
    if lineweight_mm >= 0.40:
        return 1.6
    return 1.0


class _Group:
    """Primitives that share layers, colour, width and tile."""
    __slots__ = ("lines", "paths", "fills", "points")

    def __init__(self):
        self.lines: List[Tuple[float, float, float, float]] = []
        self.paths: list = []                 # NumpyPath2d (stroked)
        self.fills: list = []                 # NumpyPath2d (filled)
        self.points: List[Tuple[float, float]] = []


def merge_recording(recorder) -> dict:
    """Group the recorded primitives (runs in the background thread: no Qt
    object is created here). Returns {"groups": {key: _Group},
    "images": [(image_data, layers)], "extents": (x0, y0, x1, y1)}."""
    from ezdxf.addons.drawing.recorder import (FilledPathsRecord,
                                               ImageRecord, PathRecord,
                                               PointsRecord, SolidLinesRecord)
    player = recorder.player()
    records = list(player.recordings())
    xs0, ys0, xs1, ys1 = [], [], [], []
    for record, _props in records:
        try:
            bb = record.bbox()
        except Exception:
            continue
        if bb.has_data:
            xs0.append(bb.extmin.x)
            ys0.append(bb.extmin.y)
            xs1.append(bb.extmax.x)
            ys1.append(bb.extmax.y)
    if not xs0:
        return {"groups": {}, "images": [], "extents": None}
    ex = (min(xs0), min(ys0), max(xs1), max(ys1))
    tw = max((ex[2] - ex[0]) / TILES, 1e-9)
    th = max((ex[3] - ex[1]) / TILES, 1e-9)

    def tile(x: float, y: float) -> Tuple[int, int]:
        return (min(TILES - 1, max(0, int((x - ex[0]) / tw))),
                min(TILES - 1, max(0, int((y - ex[1]) / th))))

    groups: Dict[tuple, _Group] = {}
    images = []

    def group(record, props, kind: str, x: float, y: float) -> _Group:
        layers = getattr(record, "vis_layers",
                         frozenset([(props.layer or "0").upper()]))
        width = 0.0 if kind == "fill" else _pen_width(props.lineweight)
        key = (layers, props.color, width, kind, tile(x, y))
        g = groups.get(key)
        if g is None:
            g = groups[key] = _Group()
        return g

    for record, props in records:
        if isinstance(record, PointsRecord):
            v = record.points.vertices()
            if not v:
                continue
            if len(v) > 2:
                from ezdxf.npshapes import NumpyPath2d
                from ezdxf.path import from_vertices
                c = v[0]
                group(record, props, "fill", c.x, c.y).fills.append(
                    NumpyPath2d(from_vertices(v, close=True)))
            elif len(v) == 2:
                group(record, props, "line", v[0].x, v[0].y).lines.append(
                    (v[0].x, v[0].y, v[1].x, v[1].y))
            else:
                group(record, props, "line", v[0].x, v[0].y).points.append(
                    (v[0].x, v[0].y))
        elif isinstance(record, SolidLinesRecord):
            pts = record.lines.vertices()
            if not pts:
                continue
            g = group(record, props, "line", pts[0].x, pts[0].y)
            for a, b in zip(pts[::2], pts[1::2]):
                g.lines.append((a.x, a.y, b.x, b.y))
        elif isinstance(record, PathRecord):
            s = record.path.start
            group(record, props, "line", s.x, s.y).paths.append(record.path)
        elif isinstance(record, FilledPathsRecord):
            if not record.paths:
                continue
            s = record.paths[0].start
            group(record, props, "fill", s.x, s.y).fills.extend(record.paths)
        elif isinstance(record, ImageRecord):
            layers = getattr(record, "vis_layers",
                             frozenset([(props.layer or "0").upper()]))
            images.append((record.image_data, layers))
    return {"groups": groups, "images": images, "extents": ex}


class _RenderThread(QThread):
    done = Signal(object)

    def __init__(self, path: str, bg: str, parent=None):
        super().__init__(parent)
        self.path, self.bg = path, bg

    def run(self) -> None:
        try:
            import ezdxf
            from ezdxf.addons.drawing import Frontend, RenderContext
            from ezdxf.addons.drawing.config import (BackgroundPolicy,
                                                     ColorPolicy,
                                                     Configuration)
            doc = ezdxf.readfile(self.path)
            rec = _make_recorder_class()()
            cfg = Configuration(background_policy=BackgroundPolicy.CUSTOM,
                                custom_bg_color=self.bg,
                                color_policy=ColorPolicy.COLOR)
            ctx = RenderContext(doc)
            Frontend(ctx, rec, config=cfg).draw_layout(doc.modelspace(),
                                                       finalize=True)
            self.done.emit({"merged": merge_recording(rec), "error": ""})
        except Exception as exc:                           # pragma: no cover
            self.done.emit({"merged": None, "error": str(exc)})


def _lines_path(lines, points) -> QPainterPath:
    path = QPainterPath()
    for x0, y0, x1, y1 in lines:
        path.moveTo(x0, y0)
        path.lineTo(x1, y1)
    for x, y in points:                     # a point: a tiny dot
        path.moveTo(x, y)
        path.lineTo(x, y)
    return path


def _image_item(image_data) -> QGraphicsPixmapItem:
    """Same as ezdxf's PyQt backend draw_image."""
    import numpy as np
    from PySide6.QtGui import QImage
    image = image_data.image
    height, width, depth = image.shape
    image = np.ascontiguousarray(np.flip(image, axis=0))
    pixmap = QPixmap(QImage(image.data, width, height, width * depth,
                            QImage.Format.Format_RGBA8888))
    item = QGraphicsPixmapItem(pixmap)
    item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
    m = image_data.transform
    item.setTransform(QTransform(m[0][0], m[0][1], m[0][3], m[1][0], m[1][1],
                                 m[1][3], m[3][0], m[3][1], m[3][3]))
    return item


class DxfView(CadView):
    loading = Signal(bool)
    loaded = Signal(str)                      # error text ('' when fine)

    def __init__(self, parent=None):
        super().__init__(parent, flip_y=True)
        self.path = ""
        self._thread: Optional[_RenderThread] = None
        self._hidden: Set[str] = set()
        self._busy = False
        self._has_content = False
        self._overlay: List[QGraphicsPixmapItem] = []
        self._overlay_opacity = 0.45
        self._message = tr("No result yet. Convert the drawing to preview "
                           "the DXF here.")
        self.setViewportUpdateMode(
            CadView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setOptimizationFlag(
            CadView.OptimizationFlag.DontAdjustForAntialiasing, True)

    def background_token(self) -> str:
        return "model_space"

    # ---- loading ------------------------------------------------------------------
    def load(self, path: str) -> None:
        self.path = path
        self.scene().clear()
        self._overlay = []
        self._has_content = False
        if not path or not os.path.isfile(path):
            self._message = tr("No result yet. Convert the drawing to "
                               "preview the DXF here.")
            self.viewport().update()
            return
        if self._thread is not None and self._thread.isRunning():
            self._thread.done.disconnect()
            self._thread.wait(50)
        self._busy = True
        self._message = tr("Rendering the DXF preview…")
        self.loading.emit(True)
        self.viewport().update()
        self._thread = _RenderThread(path, theme.tok("model_space"), self)
        self._thread.done.connect(self._on_rendered)
        self._thread.start()

    def clear(self) -> None:
        self.load("")

    def reload(self) -> None:
        self.load(self.path)

    def _on_rendered(self, result: dict) -> None:
        self._busy = False
        self.loading.emit(False)
        merged = result.get("merged")
        if merged is None:
            self._message = result.get("error") or "?"
            self.viewport().update()
            self.loaded.emit(self._message)
            return
        self.scene().clear()
        self._overlay = []
        self.setUpdatesEnabled(False)
        try:
            self._build_items(merged)
        finally:
            self.setUpdatesEnabled(True)
        self._has_content = True
        self._apply_visibility()
        self.fit()
        self.loaded.emit("")

    def _build_items(self, merged: dict) -> None:
        from ezdxf.npshapes import to_qpainter_path
        scene = self.scene()
        for (layers, color, width, kind, _tile), g in \
                merged["groups"].items():
            qcolor = QColor(color[:7])
            if len(color) == 9:                 # #RRGGBBAA
                qcolor.setAlpha(int(color[7:9], 16))
            if kind == "fill":
                path = to_qpainter_path(g.fills)
                path.setFillRule(Qt.FillRule.OddEvenFill)
                item = QGraphicsPathItem(path)
                item.setPen(QPen(Qt.PenStyle.NoPen))
                item.setBrush(QBrush(qcolor))
            else:
                path = _lines_path(g.lines, g.points)
                if g.paths:
                    path.addPath(to_qpainter_path(g.paths))
                item = QGraphicsPathItem(path)
                pen = QPen(qcolor, width)
                pen.setCosmetic(True)           # constant on screen
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                item.setPen(pen)
            item.setData(LAYERS_ROLE, layers)
            scene.addItem(item)
        for image_data, layers in merged["images"]:
            try:
                item = _image_item(image_data)
            except Exception:                              # pragma: no cover
                continue
            item.setZValue(-1)
            item.setData(LAYERS_ROLE, layers)
            scene.addItem(item)

    # ---- overlay check -------------------------------------------------------------
    def set_overlay(self, sheets: List[Tuple[QPixmap, float, float, float]],
                    opacity: Optional[float] = None) -> None:
        """Show PDF sheets under the DXF: (pixmap, x_offset, top_y,
        units_per_pixel) each, in drawing units. Empty list = no overlay."""
        for item in self._overlay:
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._overlay = []
        if opacity is not None:
            self._overlay_opacity = opacity
        for pixmap, x_off, top_y, upp in sheets:
            item = QGraphicsPixmapItem(pixmap)
            item.setTransformationMode(
                Qt.TransformationMode.SmoothTransformation)
            item.setTransform(QTransform.fromScale(upp, -upp))
            item.setPos(x_off, top_y)
            item.setZValue(-10)
            item.setOpacity(self._overlay_opacity)
            self.scene().addItem(item)
            self._overlay.append(item)
        self.viewport().update()

    def set_overlay_opacity(self, opacity: float) -> None:
        self._overlay_opacity = opacity
        for item in self._overlay:
            item.setOpacity(opacity)

    def has_overlay(self) -> bool:
        return bool(self._overlay)

    def content_rect(self) -> QRectF:
        rect = QRectF()
        for item in self.scene().items():
            if item in self._overlay:
                continue
            rect = rect.united(item.sceneBoundingRect())
        return rect if not rect.isNull() else self.scene().itemsBoundingRect()

    # ---- layers ----------------------------------------------------------------------
    def set_hidden_layers(self, hidden: Set[str]) -> None:
        self._hidden = {h.upper() for h in hidden}
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        hidden = self._hidden
        for item in self.scene().items():
            layers: FrozenSet[str] = item.data(LAYERS_ROLE)
            if layers:
                item.setVisible(not (layers & hidden))

    def item_count(self) -> int:
        return len(self.scene().items())

    # ---- overlay message ---------------------------------------------------------------
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._has_content and not self._busy:
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(theme.tok("text_muted")))
        painter.setFont(theme.ui_font(10.0, QFont.Weight.Normal))
        painter.drawText(self.viewport().rect().adjusted(40, 40, -40, -40),
                         Qt.AlignmentFlag.AlignCenter
                         | Qt.TextFlag.TextWordWrap, self._message)
        painter.restore()


def overlay_scale(width_pt: float, scale: float, pixels: int) -> float:
    """Drawing units per overlay pixel for a sheet rendered `pixels` wide."""
    return (width_pt * scale) / max(pixels, 1)


__all__ = ["DxfView", "merge_recording", "overlay_scale", "LAYERS_ROLE"]
