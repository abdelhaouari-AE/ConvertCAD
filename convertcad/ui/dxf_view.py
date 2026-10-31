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

Selection: a click (without dragging) on a line, text, hatch… selects the
DXF entity under the cursor — it is highlighted and `selected` tells the
window its type, layer and main dimension (read-only: nothing is edited).
The merged items cannot tell entities apart, so the render thread also keeps
a light "pick index": every primitive segment and filled outline, with the
top-level entity it comes from.
"""

import math
import os
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsPixmapItem

from ..i18n import tr
from . import theme
from .cadview import CadView

LAYERS_ROLE = int(Qt.ItemDataRole.UserRole) + 40
TILES = 8                                   # screen tiles per side (culling)
PICK_PIXELS = 5                             # click tolerance (screen pixels)
CLICK_MOVE = 4                              # more movement = a pan, not a click


def _make_recorder_class():
    """Recorder that also records which layers each primitive belongs to
    (its own layer + the layers of the INSERTs it is nested in)."""
    from ezdxf.addons.drawing.recorder import Recorder

    class LayerRecorder(Recorder):
        def __init__(self):
            super().__init__()
            self._stack: List[str] = []
            self.entities: List[dict] = []      # top-level entities
            self._top = -1                      # index of the current one

        def enter_entity(self, entity, properties) -> None:
            if not self._stack:                 # a model-space entity
                self.entities.append(describe_entity(entity))
                self._top = len(self.entities) - 1
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
            record.owner = self._top

    return LayerRecorder


def describe_entity(entity) -> dict:
    """What the window shows about a selected entity (read-only)."""
    info = {"handle": "", "type": "", "layer": "0"}
    try:
        info.update(handle=entity.dxf.handle or "", type=entity.dxftype(),
                    layer=entity.dxf.get("layer", "0"))
        kind = info["type"]
        if kind == "LINE":
            info["length"] = (entity.dxf.end - entity.dxf.start).magnitude
        elif kind in ("CIRCLE", "ARC"):
            info["radius"] = float(entity.dxf.radius)
        elif kind == "TEXT":
            info["text"] = entity.dxf.text
        elif kind == "MTEXT":
            info["text"] = entity.plain_text().split("\n")[0]
        elif kind in ("DIMENSION", "ARC_DIMENSION"):
            override = entity.dxf.get("text", "")
            if override and override not in ("<>", " "):
                info["text"] = override.replace("<>", "").strip() or override
            else:
                try:                  # (ezdxf cannot measure every kind)
                    info["measurement"] = float(entity.get_measurement() or 0)
                except Exception:
                    pass
        elif kind == "INSERT":
            info["block"] = entity.dxf.name
        elif kind == "HATCH":
            info["pattern"] = entity.dxf.pattern_name
        elif kind == "LWPOLYLINE":
            info["vertices"] = len(entity)
        if kind in _GEOMETRY_TYPES:
            info["geom"] = _true_geometry(entity)
    except Exception:                                      # pragma: no cover
        pass
    return info


# entities selectable along their whole geometry, not only where ink is
# drawn (the gaps of a dashed or centre line belong to the line too)
_GEOMETRY_TYPES = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE",
                   "SPLINE", "ELLIPSE"}


def _true_geometry(entity) -> List[List[Tuple[float, float]]]:
    from ezdxf import path as ezpath
    pth = ezpath.make_path(entity)
    pts = list(pth.control_vertices())
    if not pts:
        return []
    xs, ys = [v.x for v in pts], [v.y for v in pts]
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    out = []
    for sub in pth.sub_paths():
        out.append([(v.x, v.y) for v in sub.flattening(size / 200.0)])
    return out


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


class _PickBuilder:
    """Collects, for selection, every drawn segment and filled outline with
    the index of the model-space entity it belongs to (numpy arrays: a
    click is answered in a few milliseconds even on 50 000 entities)."""

    def __init__(self, entities: List[dict], size: float):
        self.entities = entities
        self.flat = max(size, 1e-9) / 4000.0     # curve flattening (units)
        self.seg_chunks: list = []               # (N x 4) arrays
        self.owner_chunks: list = []
        self.polys: List[tuple] = []             # (owner, Nx2 array, area)
        self.layers: Dict[int, set] = {}

    def _lines(self, owner: int, pts) -> None:
        """A polyline (N x 2 array or list of points) -> N-1 segments."""
        import numpy as np
        arr = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if len(arr) < 2:
            return
        self.seg_chunks.append(np.hstack([arr[:-1], arr[1:]]))
        self.owner_chunks.append(np.full(len(arr) - 1, owner, np.int64))

    def _poly(self, owner: int, pts) -> None:
        import numpy as np
        arr = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if len(arr) < 3:
            return
        x, y = arr[:, 0], arr[:, 1]                     # shoelace formula
        area = 0.5 * abs(float(np.dot(x[:-1], y[1:]) - np.dot(y[:-1], x[1:])
                               + x[-1] * y[0] - y[-1] * x[0]))
        self.polys.append((owner, arr, area))

    def _path_arrays(self, path) -> list:
        import numpy as np
        subs = path.sub_paths() if path.has_sub_paths else [path]
        out = []
        for sub in subs:
            if not sub.has_curves:
                out.append(sub.np_vertices()[:, :2])
                continue
            try:
                out.append(np.array([(v.x, v.y)
                                     for v in sub.flattening(self.flat)]))
            except Exception:                              # pragma: no cover
                out.append(sub.np_vertices()[:, :2])
        return out

    def add(self, record) -> None:
        import numpy as np
        (FilledPathsRecord, ImageRecord, PathRecord, PointsRecord,
         SolidLinesRecord) = _record_types()
        owner = getattr(record, "owner", -1)
        if owner < 0:
            return
        self.layers.setdefault(owner, set()).update(
            getattr(record, "vis_layers", ()))
        try:
            if isinstance(record, PointsRecord):
                v = record.points.np_vertices()[:, :2]
                if len(v) > 2:
                    self._poly(owner, v)
                    self._lines(owner, np.vstack([v, v[:1]]))
                elif len(v) == 2:
                    self._lines(owner, v)
                elif len(v):
                    self._lines(owner, np.vstack([v, v]))
            elif isinstance(record, SolidLinesRecord):
                v = record.lines.np_vertices()[:, :2]
                n = len(v) // 2
                if n:
                    self.seg_chunks.append(v[:2 * n].reshape(n, 4))
                    self.owner_chunks.append(np.full(n, owner, np.int64))
            elif isinstance(record, PathRecord):
                for arr in self._path_arrays(record.path):
                    self._lines(owner, arr)
            elif isinstance(record, FilledPathsRecord):
                for path in record.paths:
                    for arr in self._path_arrays(path):
                        self._poly(owner, arr)
                        if len(arr):
                            self._lines(owner, np.vstack([arr, arr[:1]]))
            elif isinstance(record, ImageRecord):
                bb = record.bbox()
                if bb.has_data:
                    x0, y0, x1, y1 = (bb.extmin.x, bb.extmin.y, bb.extmax.x,
                                      bb.extmax.y)
                    self._poly(owner, [(x0, y0), (x1, y0), (x1, y1),
                                       (x0, y1)])
                    self.entities[owner]["image"] = True
        except Exception:                                  # pragma: no cover
            pass

    def finish(self) -> "PickIndex":
        import numpy as np
        for i, e in enumerate(self.entities):          # whole true geometry
            for pts in e.pop("geom", None) or ():
                self._lines(i, pts)
        if self.seg_chunks:
            segs = np.vstack(self.seg_chunks)
            owners = np.concatenate(self.owner_chunks)
        else:
            segs, owners = np.zeros((0, 4)), np.zeros(0, np.int64)
        for i, e in enumerate(self.entities):
            e["layers"] = frozenset(self.layers.get(i, {e["layer"].upper()}))
        return PickIndex(self.entities, segs, owners, self.polys)


_RECORD_TYPES: tuple = ()


def _record_types() -> tuple:
    global _RECORD_TYPES
    if not _RECORD_TYPES:
        from ezdxf.addons.drawing.recorder import (FilledPathsRecord,
                                                   ImageRecord, PathRecord,
                                                   PointsRecord,
                                                   SolidLinesRecord)
        _RECORD_TYPES = (FilledPathsRecord, ImageRecord, PathRecord,
                         PointsRecord, SolidLinesRecord)
    return _RECORD_TYPES


def build_pick_index(recorder, extents) -> "PickIndex":
    """The selection index of a recorded drawing (run in the background,
    after the preview is shown)."""
    size = max(extents[2] - extents[0], extents[3] - extents[1]) \
        if extents else 1.0
    pick = _PickBuilder(getattr(recorder, "entities", []), size)
    for record, _props in recorder.player().recordings():
        pick.add(record)
    return pick.finish()


class PickIndex:
    """Finds the entity under a point (drawing coordinates)."""

    def __init__(self, entities, segs, owners, polys):
        import numpy as np
        self.entities = entities
        self.segs, self.owners, self.polys = segs, owners, polys
        if len(segs):
            self._lo = np.minimum(segs[:, 0:2], segs[:, 2:4])
            self._hi = np.maximum(segs[:, 0:2], segs[:, 2:4])

    def pick(self, x: float, y: float, tol: float,
             hidden: FrozenSet[str] = frozenset()) -> int:
        """Index of the entity at (x, y), or -1. Lines and texts within
        `tol` win (the nearest); else the smallest filled area containing
        the point (hatches); images only when nothing else is there."""
        import numpy as np

        def visible(i: int) -> bool:
            return not (self.entities[i]["layers"] & hidden)
        if len(self.segs):
            near = np.nonzero((self._lo[:, 0] - tol <= x)
                              & (x <= self._hi[:, 0] + tol)
                              & (self._lo[:, 1] - tol <= y)
                              & (y <= self._hi[:, 1] + tol))[0]
            if len(near):
                s = self.segs[near]
                dx, dy = s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]
                ll = dx * dx + dy * dy
                t = np.where(ll > 0, ((x - s[:, 0]) * dx + (y - s[:, 1]) * dy)
                             / np.where(ll > 0, ll, 1.0), 0.0)
                t = np.clip(t, 0.0, 1.0)
                d = np.hypot(s[:, 0] + t * dx - x, s[:, 1] + t * dy - y)
                for k in np.argsort(d):
                    if d[k] > tol:
                        break
                    owner = int(self.owners[near[k]])
                    if visible(owner) and \
                            not self.entities[owner].get("image"):
                        return owner
        best, best_area = -1, math.inf
        images = []
        for owner, arr, area in self.polys:
            if area >= best_area or not visible(owner):
                continue
            if not (arr[:, 0].min() <= x <= arr[:, 0].max()
                    and arr[:, 1].min() <= y <= arr[:, 1].max()):
                continue
            if not _inside(arr, x, y):
                continue
            if self.entities[owner].get("image"):
                images.append((area, owner))
                continue
            best, best_area = owner, area
        if best < 0 and images:
            best = min(images)[1]
        return best

    def outline(self, owner: int) -> QPainterPath:
        """The drawn geometry of one entity (for the highlight)."""
        import numpy as np
        path = QPainterPath()
        for x0, y0, x1, y1 in self.segs[np.nonzero(self.owners == owner)[0]]:
            path.moveTo(x0, y0)
            path.lineTo(x1, y1)
        return path

    def fills(self, owner: int) -> QPainterPath:
        path = QPainterPath()
        for o, arr, _a in self.polys:
            if o != owner:
                continue
            path.moveTo(QPointF(arr[0, 0], arr[0, 1]))
            for px, py in arr[1:]:
                path.lineTo(QPointF(px, py))
            path.closeSubpath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        return path

    def bbox(self, owner: int) -> Optional[Tuple[float, float, float, float]]:
        import numpy as np
        sel = self.segs[np.nonzero(self.owners == owner)[0]]
        pts = [sel[:, 0:2], sel[:, 2:4]] if len(sel) else []
        pts += [arr for o, arr, _a in self.polys if o == owner]
        if not pts:
            return None
        allp = np.vstack(pts)
        return (float(allp[:, 0].min()), float(allp[:, 1].min()),
                float(allp[:, 0].max()), float(allp[:, 1].max()))


def _inside(poly, x: float, y: float) -> bool:
    """Even-odd point-in-polygon test (ray casting), numpy."""
    import numpy as np
    xs, ys = poly[:, 0], poly[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = ((ys > y) != (yj > y))
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = (xj - xs) * (y - ys) / (yj - ys) + xs
    return bool(np.count_nonzero(cross & (x < xi)) % 2)


class _RenderThread(QThread):
    done = Signal(object)
    pick_ready = Signal(object)             # PickIndex, after `done`

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
            merged = merge_recording(rec)
            self.done.emit({"merged": merged, "error": ""})
        except Exception as exc:                           # pragma: no cover
            self.done.emit({"merged": None, "error": str(exc)})
            return
        try:                                 # selection: ready a moment later
            self.pick_ready.emit(build_pick_index(rec, merged["extents"]))
        except Exception:                                  # pragma: no cover
            self.pick_ready.emit(None)


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
    selected = Signal(object)                 # entity info dict, or None

    def __init__(self, parent=None):
        super().__init__(parent, flip_y=True)
        self.path = ""
        self._thread: Optional[_RenderThread] = None
        self._hidden: Set[str] = set()
        self._pick: Optional[PickIndex] = None
        self._selected = -1
        self._highlight: List[QGraphicsPathItem] = []
        self._press = None                    # where the left button went down
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

    # ---- AutoCAD-like model space: dark blue-grey with a grid ---------------
    # Same colour in both themes (AutoCAD's default model space, RGB 33 40 48).
    # Grid lines every 1, 2 or 5 x 10^k drawing units, at least 14 px apart;
    # a major line every 5 lines, like AutoCAD; the X and Y axes through the
    # origin in red and green.
    GRID_MINOR = QColor(43, 51, 61)
    GRID_MAJOR = QColor(55, 65, 78)
    AXIS_X = QColor(115, 52, 52)
    AXIS_Y = QColor(52, 105, 60)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.qcolor("model_space"))
        if not self._has_content:
            return
        px = self.current_scale()                     # pixels per unit
        if px <= 0:
            return
        step = 10 ** math.floor(math.log10(14.0 / px))
        for k in (1, 2, 5, 10):
            if step * k * px >= 14.0:
                step *= k
                break
        x0 = math.floor(rect.left() / step)
        x1 = math.ceil(rect.right() / step)
        y0 = math.floor(rect.top() / step)
        y1 = math.ceil(rect.bottom() / step)
        if (x1 - x0) + (y1 - y0) > 1200:              # never too many lines
            return
        painter.save()
        minor = QPen(self.GRID_MINOR, 0)
        major = QPen(self.GRID_MAJOR, 0)
        for i in range(x0, x1 + 1):
            painter.setPen(major if i % 5 == 0 else minor)
            x = i * step
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for j in range(y0, y1 + 1):
            painter.setPen(major if j % 5 == 0 else minor)
            y = j * step
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        if rect.top() <= 0 <= rect.bottom():
            painter.setPen(QPen(self.AXIS_X, 0))
            painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
        if rect.left() <= 0 <= rect.right():
            painter.setPen(QPen(self.AXIS_Y, 0))
            painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
        painter.restore()

    # ---- loading ------------------------------------------------------------------
    def load(self, path: str) -> None:
        self.path = path
        self._forget_selection()
        self._pick = None
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
            self._thread.pick_ready.disconnect()
            self._thread.wait(50)
        self._busy = True
        self._message = tr("Rendering the DXF preview…")
        self.loading.emit(True)
        self.viewport().update()
        self._thread = _RenderThread(path, theme.tok("model_space"), self)
        self._thread.done.connect(self._on_rendered)
        self._thread.pick_ready.connect(self._on_pick_ready)
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
        self._forget_selection()
        self.scene().clear()
        self._overlay = []
        self._pick = None                      # see _on_pick_ready
        self.setUpdatesEnabled(False)
        try:
            self._build_items(merged)
        finally:
            self.setUpdatesEnabled(True)
        self._has_content = True
        self._apply_visibility()
        self.fit()
        self.loaded.emit("")

    def _on_pick_ready(self, pick) -> None:
        self._pick = pick

    def selection_ready(self) -> bool:
        return self._pick is not None

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
        if self._selected >= 0 and self._pick is not None and \
                self._pick.entities[self._selected]["layers"] & hidden:
            self.clear_selection()                # its layer was hidden

    # ---- selection (read-only) -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        self._press = (event.position()
                       if event.button() == Qt.MouseButton.LeftButton
                       else None)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        press, self._press = self._press, None
        super().mouseReleaseEvent(event)
        if press is not None and event.button() == Qt.MouseButton.LeftButton:
            d = event.position() - press
            if abs(d.x()) + abs(d.y()) <= CLICK_MOVE:   # a click, not a pan
                self.select_at(event.position())

    def select_at(self, view_pos) -> int:
        """Select the entity under a viewport position (or clear the
        selection on empty space). Returns its index, -1 when none."""
        if self._pick is None or not self._has_content:
            return -1
        p = self.mapToScene(QPointF(view_pos).toPoint())
        tol = PICK_PIXELS / max(self.current_scale(), 1e-12)
        idx = self._pick.pick(p.x(), p.y(), tol, frozenset(self._hidden))
        if idx < 0:
            self.clear_selection()
        else:
            self.select_index(idx)
        return idx

    def select_index(self, idx: int) -> None:
        self._forget_selection()
        self._selected = idx
        color = theme.qcolor("selection")
        halo = QColor(color)
        halo.setAlpha(90)
        fills = self._pick.fills(idx)
        if not fills.isEmpty():
            fill_item = QGraphicsPathItem(fills)
            fill_item.setPen(QPen(Qt.PenStyle.NoPen))
            tint = QColor(color)
            tint.setAlpha(60)
            fill_item.setBrush(QBrush(tint))
            self._highlight.append(fill_item)
        outline = self._pick.outline(idx)
        for width, c in ((7.0, halo), (2.0, color)):
            item = QGraphicsPathItem(outline)
            pen = QPen(c, width)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            item.setPen(pen)
            self._highlight.append(item)
        for z, item in enumerate(self._highlight):
            item.setZValue(1000 + z)
            self.scene().addItem(item)
        info = dict(self._pick.entities[idx])
        info["bbox"] = self._pick.bbox(idx)
        info.pop("layers", None)
        self.selected.emit(info)

    def clear_selection(self) -> None:
        had = self._selected >= 0
        self._forget_selection()
        if had:
            self.selected.emit(None)

    def _forget_selection(self) -> None:
        for item in self._highlight:
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._highlight = []
        self._selected = -1

    def selected_index(self) -> int:
        return self._selected

    def item_count(self) -> int:
        return len(self.scene().items())

    # ---- overlay message ---------------------------------------------------------------
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._has_content and not self._busy:
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(160, 172, 186))          # on the dark model space
        painter.setFont(theme.ui_font(10.0, QFont.Weight.Normal))
        painter.drawText(self.viewport().rect().adjusted(40, 40, -40, -40),
                         Qt.AlignmentFlag.AlignCenter
                         | Qt.TextFlag.TextWordWrap, self._message)
        painter.restore()


def overlay_scale(width_pt: float, scale: float, pixels: int) -> float:
    """Drawing units per overlay pixel for a sheet rendered `pixels` wide."""
    return (width_pt * scale) / max(pixels, 1)


__all__ = ["DxfView", "PickIndex", "build_pick_index", "describe_entity",
           "merge_recording", "overlay_scale", "LAYERS_ROLE"]
