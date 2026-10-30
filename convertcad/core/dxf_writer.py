"""
dxf_writer.py — STEP 6: write the final DXF with ezdxf.

The single place where:
  * the Y axis is flipped (page y-down -> DXF y-up)
  * page points are scaled to real-world units (mm / cm / m)
  * colours become CAD colours (AutoCAD Color Index or true colour; black
    and white always become ACI 7, which adapts to the CAD background)
  * entities, layers, linetypes, blocks, dimensions, leaders, hatches,
    images and text are emitted — with R12-compatible fallbacks.

Everything upstream works in page coordinates, so changing units or scale
never touches the recognition logic.
"""

import logging
import math
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import ezdxf
from ezdxf import colors as ezcolors
from ezdxf.math import BSpline, Vec2, Vec3

from .annotations import (AngularDimension, AnnotationResult, DimensionEntity,
                          LeaderEntity, RadialDimension)
from .blocks import BlockResult
from .constants import (LAYER_BLOCKS, LAYER_DIM, LAYER_DIM_RAW, LAYER_HATCH,
                        LAYER_IMAGE, LAYER_LEADER, LAYER_SHX_TEXT, LAYER_TEXT,
                        LAYER_TRACE_TEXT, UNITS)
from .extractor import PageData, RawText, Style
from .geometry import EArc, ECircle, EPolyline, ESpline, RebuiltPage
from .patterns import parse_dash_pattern
from .layers import LayerInfo, build_layer_table, layer_for_style, lineweight_enum
from .spatial import angle_diff_mod180
from .stats import WriteStats
from .units import compute_scale, effective_denominator  # noqa: F401 (re-export)

TEXT_STYLE = "ConvertCAD"
TEXT_FONT = "arial.ttf"

# ezdxf logs informational notes (e.g. "$INSUNITS not exported for R12")
logging.getLogger("ezdxf").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Coordinates and scale
# ---------------------------------------------------------------------------
class Transform:
    """Page coords (pt, y down) -> DXF model space (units, y up)."""

    def __init__(self, page_height_pt: float, scale: float,
                 x_offset: float = 0.0):
        self.h = page_height_pt
        self.s = scale                       # real units per page point
        self.dx = x_offset                   # multi-page horizontal layout

    def pt(self, p: Tuple[float, float]) -> Tuple[float, float]:
        return (p[0] * self.s + self.dx, (self.h - p[1]) * self.s)

    def length(self, v: float) -> float:
        return v * self.s

    def arc_angles(self, start: float, end: float) -> Tuple[float, float]:
        """Y flip reverses sweep: CCW(a1->a2, y-down) == CCW(-a2->-a1, y-up)."""
        return (-end) % 360.0, (-start) % 360.0


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
_ACI_CACHE: Dict[Tuple[int, int, int], int] = {}
_GRAYS = (8, 9, 250, 251, 252, 253, 254)
_ACI_GRAY = [(i, tuple(ezcolors.aci2rgb(i))) for i in _GRAYS]
_ACI_CHROMA = [(i, tuple(ezcolors.aci2rgb(i))) for i in range(1, 250)
               if i not in (7, 8, 9)]


def is_neutral(rgb) -> bool:
    """Black or white: becomes ACI 7 (black on white paper, white on screen)."""
    return max(rgb) < 40 or min(rgb) > 235


def _redmean(c1, c2) -> float:
    """Cheap perceptual colour distance ("redmean" approximation)."""
    rm = (c1[0] + c2[0]) / 2.0
    dr, dg, db = c1[0] - c2[0], c1[1] - c2[1], c1[2] - c2[2]
    return (2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) \
        * db * db


def nearest_aci(rgb) -> int:
    """Closest AutoCAD Color Index. Greys map to grey indices, colours to
    colour indices (a pale blue never becomes white)."""
    rgb = tuple(int(c) for c in rgb[:3])
    if is_neutral(rgb):
        return 7
    hit = _ACI_CACHE.get(rgb)
    if hit is None:
        mx, mn = max(rgb), min(rgb)
        sat = (mx - mn) / mx if mx else 0.0
        table = _ACI_GRAY if sat < 0.12 else _ACI_CHROMA
        hit = min(table, key=lambda it: _redmean(it[1], rgb))[0]
        _ACI_CACHE[rgb] = hit
    return hit


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------
@dataclass
class WriterSettings:
    dxf_version: str = "R2018"
    units: str = "mm"
    layer_mode: str = "style"            # style | color | single
    use_pdf_layers: bool = True
    color_mode: str = "aci"              # aci | true
    text_height_factor: float = 0.7      # cap height / font size
    effective_scale: float = 50.0        # 1:N, used for LTSCALE
    ignore_white_fills: bool = True
    ignore_background_fills: bool = True


class DxfWriter:
    _EXTRA_LINETYPES = {
        "HIDDEN": ("Hidden __ __ __ __", [0.375, 0.25, -0.125]),
        "DASHDOT": ("Dash dot __ . __ . __", [0.5, 0.25, -0.125, 0.0, -0.125]),
        "CENTER": ("Center ____ _ ____ _", [1.25, 0.75, -0.25, 0.25, -0.25]),
        "PHANTOM": ("Phantom ___ _ _ ___",
                    [1.25, 0.625, -0.125, 0.125, -0.125, 0.125, -0.125]),
        "DASHED": ("Dashed __ __ __", [0.75, 0.5, -0.25]),
    }

    def __init__(self, settings: Optional[WriterSettings] = None):
        self.s = settings or WriterSettings()
        self.r12 = self.s.dxf_version == "R12"
        if self.s.dxf_version in ("R12", "R2000"):
            self.s.color_mode = "aci"                 # true colour: R2004+
        self.doc = ezdxf.new(self.s.dxf_version, setup=["linetypes"])
        self.msp = self.doc.modelspace()
        self.stats = WriteStats()
        self._block_counter = 0
        self._layer_rgb: Dict[str, Tuple[int, int, int]] = {}
        self._layer_lt: Dict[str, str] = {}
        self._layer_lw: Dict[str, int] = {}
        self._custom_lt: Dict[tuple, str] = {}      # measured linetypes
        self._warned: set = set()
        self._setup_document()

    # ---- document setup ------------------------------------------------------
    def _setup_document(self) -> None:
        for name, (desc, pattern) in self._EXTRA_LINETYPES.items():
            if name not in self.doc.linetypes:
                try:
                    self.doc.linetypes.add(name, pattern=pattern,
                                           description=desc)
                except Exception as exc:                   # pragma: no cover
                    self.stats.warnings.append(f"Linetype {name}: {exc}")
        if TEXT_STYLE not in self.doc.styles:
            self.doc.styles.add(TEXT_STYLE, font=TEXT_FONT)
        hdr = self.doc.header
        if not self.r12:
            hdr["$INSUNITS"] = UNITS.get(self.s.units, UNITS["mm"])["insunits"]
        hdr["$MEASUREMENT"] = 1                            # metric
        hdr["$LUNITS"] = 2                                 # decimal
        factor = UNITS.get(self.s.units, UNITS["mm"])["factor"]
        # 1 linetype-pattern unit ~ 10 mm on paper at the drawing scale
        hdr["$LTSCALE"] = max(10.0 * self.s.effective_scale * factor, 1e-6)
        hdr["$PSLTSCALE"] = 1
        hdr["$TEXTSTYLE"] = TEXT_STYLE

    def set_ltscale(self, effective_scale: float) -> None:
        """Linetype scale for a drawing scale of 1:effective_scale."""
        self.s.effective_scale = effective_scale
        factor = UNITS.get(self.s.units, UNITS["mm"])["factor"]
        self.doc.header["$LTSCALE"] = max(10.0 * effective_scale * factor,
                                          1e-6)

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.stats.warnings.append(msg)

    # ---- layers --------------------------------------------------------------
    def ensure_layers(self, table: Dict[str, LayerInfo]) -> None:
        for info in table.values():
            self.ensure_layer(info)

    def ensure_layer(self, info: LayerInfo) -> None:
        if info.name in self.doc.layers:
            return
        layer = self.doc.layers.add(info.name)
        aci = nearest_aci(info.rgb)
        layer.color = aci
        if self.s.color_mode == "true" and not is_neutral(info.rgb):
            layer.rgb = info.rgb
        lt = info.linetype if info.linetype in self.doc.linetypes \
            else "Continuous"
        layer.dxf.linetype = lt
        if info.lineweight >= 0 and not self.r12:
            layer.dxf.lineweight = info.lineweight
        if info.locked:
            layer.lock()
        if info.off:
            layer.off()
        if info.description and not self.r12:
            try:
                layer.description = info.description
            except Exception:                              # pragma: no cover
                pass
        self._layer_rgb[info.name] = tuple(info.rgb)
        self._layer_lt[info.name] = lt
        self._layer_lw[info.name] = info.lineweight
        self.stats.layers.append(info.name)

    def _role_layer(self, name: str, rgb=(0, 0, 0), locked=False) -> str:
        self.ensure_layer(LayerInfo(name, rgb, locked=locked))
        return name

    def prepare_layers(self, rp: RebuiltPage) -> None:
        """Create every geometry layer of a page before writing anything."""
        self.ensure_layers(build_layer_table(
            rp.all_styles(), use_pdf_layers=self.s.use_pdf_layers,
            mode=self.s.layer_mode))

    def _count(self, layer: str) -> None:
        self.stats.layer_counts[layer] = self.stats.layer_counts.get(layer, 0) + 1

    # ---- attributes ----------------------------------------------------------
    def _color_attribs(self, rgb, layer: str) -> dict:
        rgb = tuple(int(c) for c in rgb[:3])
        lrgb = self._layer_rgb.get(layer)
        if lrgb is not None:
            if self.s.color_mode == "true":
                same = (rgb == lrgb or (is_neutral(rgb) and is_neutral(lrgb)))
            else:
                same = nearest_aci(rgb) == nearest_aci(lrgb)
            if same:
                return {"color": 256}                      # ByLayer
        if self.s.color_mode == "true" and not is_neutral(rgb):
            return {"color": nearest_aci(rgb),
                    "true_color": ezcolors.rgb2int(rgb)}
        return {"color": nearest_aci(rgb)}

    def _attribs(self, style: Style, layer: str, tr=None) -> dict:
        att = {"layer": layer}
        att.update(self._color_attribs(style.color, layer))
        lt = self._linetype_of(style, tr)
        if lt.upper() != self._layer_lt.get(layer, "Continuous").upper():
            att["linetype"] = lt
        if not self.r12:
            lw = lineweight_enum(style.width)
            if lw != self._layer_lw.get(layer, -1):
                att["lineweight"] = lw
        return att

    def _linetype_of(self, style: Style, tr=None) -> str:
        """Linetype of an entity: the dashes measured on the PDF when the
        line was rebuilt from pieces (patterns.py), else the named type."""
        elements = parse_dash_pattern(style.dash_pattern)
        if elements and tr is not None:
            name = self._measured_linetype(style.linetype, elements,
                                           tr.length(1.0))
            if name:
                return name
        return style.linetype if style.linetype in self.doc.linetypes \
            else "Continuous"

    def _measured_linetype(self, family: str, elements_pt, units_per_pt
                           ) -> str:
        """Register (once) a linetype reproducing the PDF dash lengths.

        Pattern lengths are divided by $LTSCALE, so at the drawing's linetype
        scale every dash has exactly its length on the PDF sheet."""
        lts = float(self.doc.header.get("$LTSCALE", 1.0) or 1.0)
        k = units_per_pt / lts
        pattern = [round(e * k, 6) for e in elements_pt]
        if not any(v > 0 for v in pattern) and not any(v == 0
                                                        for v in pattern):
            return ""
        key = (family, tuple(pattern))
        name = self._custom_lt.get(key)
        if name is None:
            n = sum(1 for kk in self._custom_lt if kk[0] == family) + 1
            name = f"CC_{family}_{n}"
            total = sum(abs(v) for v in pattern)
            try:
                self.doc.linetypes.add(
                    name, pattern=[total] + pattern,
                    description=f"{family.title()} (measured on the PDF)")
            except Exception:                              # pragma: no cover
                return ""
            self._custom_lt[key] = name
        return name

    def _layer_of(self, style: Style) -> str:
        return layer_for_style(style, self.s.use_pdf_layers, self.s.layer_mode)

    # ---- geometry --------------------------------------------------------------
    def write_geometry(self, rp: RebuiltPage, tr: Transform) -> None:
        for pl in rp.polylines:
            if not pl.consumed:
                self._write_polyline(pl, tr, self._layer_of(pl.style))
        for a in rp.arcs:
            if not a.consumed:
                self._write_arc(a, tr, self._layer_of(a.style))
        for c in rp.circles:
            if not c.consumed:
                self._write_circle(c, tr, self._layer_of(c.style))
        for s in rp.splines:
            if not s.consumed:
                self._write_spline(s, tr, self._layer_of(s.style))
        self.stats.duplicates_removed += rp.duplicates_removed
        self.stats.dashed_lines += rp.dashed_lines
        self.stats.dash_pieces_merged += rp.dash_pieces

    def _write_polyline(self, pl: EPolyline, tr, layer: str, target=None,
                        count=True) -> None:
        target = self.msp if target is None else target
        pts = [tr.pt(p) for p in pl.points]
        att = self._attribs(pl.style, layer, tr)
        if len(pts) == 2 and not pl.closed:
            target.add_line(pts[0], pts[1], dxfattribs=att)
            if count:
                self.stats.lines += 1
        elif self.r12:
            target.add_polyline2d(pts, close=pl.closed, dxfattribs=att)
            if count:
                self.stats.polylines += 1
        else:
            target.add_lwpolyline(pts, close=pl.closed, dxfattribs=att)
            if count:
                self.stats.polylines += 1
        if count:
            self._count(layer)

    def _write_arc(self, a: EArc, tr, layer: str, target=None, count=True):
        target = self.msp if target is None else target
        sa, ea = tr.arc_angles(a.start_angle, a.end_angle)
        target.add_arc(center=tr.pt(a.center), radius=tr.length(a.radius),
                       start_angle=sa, end_angle=ea,
                       dxfattribs=self._attribs(a.style, layer, tr))
        if count:
            self.stats.arcs += 1
            self._count(layer)

    def _write_circle(self, c: ECircle, tr, layer: str, target=None,
                      count=True):
        target = self.msp if target is None else target
        target.add_circle(center=tr.pt(c.center), radius=tr.length(c.radius),
                          dxfattribs=self._attribs(c.style, layer, tr))
        if count:
            self.stats.circles += 1
            self._count(layer)

    def _write_spline(self, s: ESpline, tr, layer: str, target=None,
                      count=True):
        target = self.msp if target is None else target
        cps = [tr.pt(p) for p in s.control_points]
        n = max(1, (len(cps) - 1) // 3)
        cps = cps[:3 * n + 1]
        att = self._attribs(s.style, layer, tr)
        try:
            # Piecewise cubic Bezier == clamped cubic B-spline with interior
            # knots of multiplicity 3: an EXACT representation.
            knots = [0, 0, 0, 0] + [k for i in range(1, n)
                                    for k in (i, i, i)] + [n] * 4
            bs = BSpline([Vec3(p[0], p[1], 0) for p in cps], order=4,
                         knots=knots)
            if self.r12:                            # no SPLINE in R12
                pts = [(v.x, v.y) for v in bs.approximate(max(8, 12 * n))]
                target.add_polyline2d(pts, dxfattribs=att)
            else:
                spline = target.add_spline(dxfattribs=att)
                spline.apply_construction_tool(bs)
            if count:
                self.stats.splines += 1
                self._count(layer)
        except Exception as exc:
            self._warn_once("spline", f"Some splines were skipped: {exc}")

    # ---- text ----------------------------------------------------------------
    def _text_height(self, t: RawText, tr) -> float:
        if t.cap_height > 0:                    # measured letters (SHX)
            return max(tr.length(t.cap_height), 1e-6)
        return max(tr.length(t.height) * self.s.text_height_factor, 1e-6)

    def write_texts(self, texts: List[RawText], consumed: set,
                    dim_raw_ids: set, tr, group_mtext: bool = True) -> None:
        by_layer: Dict[str, List[RawText]] = {}
        for t in texts:
            if id(t) in consumed:
                continue
            if id(t) in dim_raw_ids:
                layer = self._role_layer(LAYER_DIM_RAW, (255, 0, 0))
            elif t.source == "ocr":
                layer = self._role_layer(LAYER_TRACE_TEXT, (0, 160, 160))
            else:
                layer = self._role_layer(LAYER_TEXT)
            by_layer.setdefault(layer, []).append(t)
        for layer, items in by_layer.items():
            if group_mtext and layer != LAYER_DIM_RAW and not self.r12:
                groups = group_text_lines(items)
            else:
                groups = [[t] for t in items]
            for grp in groups:
                if len(grp) == 1:
                    self._write_text(grp[0], layer, tr)
                else:
                    self._write_mtext(grp, layer, tr)

    def write_shx_texts(self, texts: List[RawText], tr,
                        default_size: float) -> None:
        if not texts:
            return
        layer = self._role_layer(LAYER_SHX_TEXT, (0, 255, 255))
        for t in texts:
            if t.height <= 0:
                t.height = default_size
            self._write_text(t, layer, tr, stat="shx_texts")

    def _write_text(self, t: RawText, layer: str, tr, stat: str = "") -> None:
        att = {"layer": layer, "height": self._text_height(t, tr),
               "rotation": t.rotation, "style": TEXT_STYLE}
        att.update(self._color_attribs(t.color, layer))
        ent = self.msp.add_text(t.text, dxfattribs=att)
        ent.set_placement(tr.pt(t.origin))
        stat = stat or ("ocr_texts" if t.source == "ocr" else "texts")
        setattr(self.stats, stat, getattr(self.stats, stat) + 1)
        self._count(layer)

    def _write_mtext(self, grp: List[RawText], layer: str, tr) -> None:
        try:
            top = grp[0]
            h = self._text_height(top, tr)
            a = math.radians(top.rotation)
            up = (-math.sin(a), -math.cos(a))               # page coords
            cap = top.height * self.s.text_height_factor
            anchor = (top.origin[0] + up[0] * cap, top.origin[1] + up[1] * cap)
            gaps = [math.dist(p.origin, q.origin) for p, q in zip(grp, grp[1:])]
            spacing = statistics.mean(gaps) if gaps else top.height * 1.2
            factor = spacing / max(cap * 5.0 / 3.0, 1e-9)
            att = {"layer": layer, "char_height": h,
                   "rotation": top.rotation, "style": TEXT_STYLE,
                   "line_spacing_factor": max(0.25, min(4.0, factor))}
            att.update(self._color_attribs(top.color, layer))
            mt = self.msp.add_mtext("\\P".join(t.text for t in grp),
                                    dxfattribs=att)
            mt.set_location(tr.pt(anchor), attachment_point=1)  # 1 = TOP LEFT
            stat = "ocr_texts" if top.source == "ocr" else "mtexts"
            setattr(self.stats, stat, getattr(self.stats, stat) + 1)
            self._count(layer)
        except Exception as exc:
            self._warn_once("mtext", f"MTEXT fallback to TEXT ({exc})")
            for t in grp:
                self._write_text(t, layer, tr)

    # ---- hatches ---------------------------------------------------------------
    def write_hatches(self, page: PageData, consumed_fills: set, tr) -> None:
        page_area = page.width * page.height
        candidates = []
        for f in page.fills:
            if id(f) in consumed_fills or len(f.points) < 3:
                continue
            if self.s.ignore_white_fills and min(f.color) > 240:
                self.stats.fills_skipped += 1
                continue
            if self.s.ignore_background_fills and (
                    f.background or f.area > 0.85 * page_area):
                self.stats.fills_skipped += 1
                continue
            candidates.append(f)
        if not candidates:
            return
        if self.r12:
            self._warn_once("r12hatch", f"{len(candidates)} solid fill(s) not "
                            "exported: HATCH does not exist in DXF R12.")
            return
        layer = self._role_layer(LAYER_HATCH, (128, 128, 128))
        for f in candidates:
            try:
                ca = self._color_attribs(f.color, layer)
                hatch = self.msp.add_hatch(color=ca.get("color", 256),
                                           dxfattribs={"layer": layer})
                if "true_color" in ca:
                    hatch.set_solid_fill(color=ca["color"], rgb=f.color)
                hatch.paths.add_polyline_path([tr.pt(p) for p in f.points],
                                              is_closed=True)
                self.stats.hatches += 1
                self._count(layer)
            except Exception as exc:
                self._warn_once("hatch", f"Some hatches were skipped: {exc}")

    def write_pattern_hatches(self, rp: RebuiltPage, tr) -> None:
        """Hatch patterns rebuilt from parallel lines (patterns.py) ->
        user-defined pattern HATCH (angle + spacing, like AutoCAD's
        "User defined" hatch), on the layer of the original lines."""
        if not rp.hatch_patterns:
            return
        if self.r12:
            self._warn_once("r12pat", "Hatch patterns kept as lines: HATCH "
                            "does not exist in DXF R12.")
            return
        from ezdxf import const
        for h in rp.hatch_patterns:
            try:
                layer = self._layer_of(h.style)
                ca = self._color_attribs(h.style.color, layer)
                # pattern direction and spacing in DXF coordinates (y up)
                a = math.radians(h.angle)
                ux, uy = math.cos(a), -math.sin(a)          # flip y
                angle = math.degrees(math.atan2(uy, ux))
                spacing = tr.length(h.spacing)
                ox, oy = tr.pt(h.origin)
                # ezdxf rotates + scales the definition by (angle, spacing):
                # give it the base point that lands on the original line
                ra = math.radians(-angle)
                bx = (ox * math.cos(ra) - oy * math.sin(ra)) / spacing
                by = (ox * math.sin(ra) + oy * math.cos(ra)) / spacing
                hatch = self.msp.add_hatch(color=ca.get("color", 256),
                                           dxfattribs={"layer": layer})
                hatch.set_pattern_fill(
                    "_USER", color=ca.get("color", 256), angle=angle,
                    scale=spacing, style=0, pattern_type=0,
                    definition=[[0.0, (bx, by), (0.0, 1.0), []]])
                if "true_color" in ca:
                    hatch.dxf.true_color = ca["true_color"]
                hatch.paths.add_polyline_path(
                    [tr.pt(p) for p in h.boundary], is_closed=True,
                    flags=const.BOUNDARY_PATH_EXTERNAL)
                for hole in h.holes:
                    hatch.paths.add_polyline_path(
                        [tr.pt(p) for p in hole], is_closed=True,
                        flags=const.BOUNDARY_PATH_DEFAULT)
                self.stats.pattern_hatches += 1
                self._count(layer)
            except Exception as exc:
                self._warn_once("pattern", f"Some hatch patterns were "
                                f"skipped: {exc}")

    # ---- images -----------------------------------------------------------------
    def write_images(self, page: PageData, tr, image_base: str) -> None:
        if not page.images:
            return
        if self.r12:
            self._warn_once("r12img", "Raster images not exported: IMAGE "
                            "does not exist in DXF R12.")
            return
        layer = self._role_layer(LAYER_IMAGE, (128, 128, 128), locked=True)
        for img in page.images:
            png_path = f"{image_base}_p{page.number}_img{img.index + 1}.png"
            try:
                with open(png_path, "wb") as fh:
                    fh.write(img.png_bytes)
                wpx, hpx = max(img.width_px, 1), max(img.height_px, 1)
                image_def = self.doc.add_image_def(
                    filename=os.path.basename(png_path),
                    size_in_pixel=(wpx, hpx))
                if img.matrix:
                    # exact placement, rotation and mirroring: the image's
                    # own matrix combined with the page rotation
                    ll, lr, ul = (_image_corner(img.matrix, tr, x, y)
                                  for x, y in ((0, 1), (1, 1), (0, 0)))
                    u_vec = ((lr[0] - ll[0]) / wpx, (lr[1] - ll[1]) / wpx)
                    v_vec = ((ul[0] - ll[0]) / hpx, (ul[1] - ll[1]) / hpx)
                    ent = self.msp.add_image(
                        image_def=image_def, insert=ll,
                        size_in_units=(math.hypot(*u_vec) * wpx,
                                       math.hypot(*v_vec) * hpx),
                        dxfattribs={"layer": layer})
                    ent.dxf.u_pixel = Vec3(u_vec[0], u_vec[1], 0)
                    ent.dxf.v_pixel = Vec3(v_vec[0], v_vec[1], 0)
                else:
                    x0, y0, x1, y1 = img.bbox
                    ll = tr.pt((x0, y1))                 # lower-left after flip
                    w, h = tr.length(x1 - x0), tr.length(y1 - y0)
                    self.msp.add_image(image_def=image_def, insert=ll,
                                       size_in_units=(w, h),
                                       dxfattribs={"layer": layer})
                self.stats.images += 1
                self.stats.image_files.append(png_path)
                self._count(layer)
            except Exception as exc:
                self._warn_once("img", f"Some images were skipped: {exc}")

    # ---- dimensions & leaders ------------------------------------------------------
    def write_annotations(self, ann: AnnotationResult, tr) -> None:
        if ann.dimensions or ann.radial or ann.angular:
            self._role_layer(LAYER_DIM, (255, 0, 0))
        for d in ann.dimensions:
            self._write_dimension(d, tr)
        for r in ann.radial:
            self._write_radial(r, tr)
        for a in ann.angular:
            self._write_angular(a, tr)
        if ann.leaders:
            self._role_layer(LAYER_LEADER, (0, 0, 255))
        for ld in ann.leaders:
            self._write_leader(ld, tr)

    def _write_dimension(self, d: DimensionEntity, tr) -> None:
        """Emit a LINEAR (rotated) dimension: its line lies exactly on the
        PDF dimension line (through the tips), whatever the depth of the
        two measured points. The value shown is the original PDF text."""
        try:
            p1, p2 = tr.pt(d.def_point1), tr.pt(d.def_point2)
            t1 = tr.pt(d.tip1 if d.tip1 is not None else d.def_point1)
            t2 = tr.pt(d.tip2 if d.tip2 is not None else d.def_point2)
            if math.dist(t1, t2) < 1e-9:
                return
            angle = math.degrees(math.atan2(t2[1] - t1[1], t2[0] - t1[0]))
            override = self._dim_override(d.height, tr)
            if d.kind == "tick":
                override["dimtsz"] = override["dimtxt"] * 0.6  # ticks
            dim = self.msp.add_linear_dim(
                base=tr.pt(d.line_point), p1=p1, p2=p2, angle=angle,
                text=d.text, dimstyle="Standard", override=override,
                dxfattribs={"layer": LAYER_DIM})
            if d.text_center is not None:
                try:
                    dim.set_location(tr.pt(d.text_center), leader=False,
                                     relative=False)
                except Exception:                          # pragma: no cover
                    pass
            dim.render()
            self.stats.dimensions += 1
            self._count(LAYER_DIM)
        except Exception as exc:
            self._warn_once("dim", f"Some dimensions fell back: {exc}")

    def _dim_override(self, height_pt: float, tr) -> dict:
        """Dimension sizes in drawing units, from the PDF text height."""
        h = max(tr.length(height_pt) * self.s.text_height_factor, 1e-6)
        return {"dimtxt": h, "dimasz": h * 0.9, "dimexe": h * 0.5,
                "dimexo": h * 0.3, "dimgap": h * 0.25,
                "dimclrd": 0, "dimclre": 0, "dimclrt": 0,
                "dimtxsty": TEXT_STYLE}

    def _undo_from(self, count: int) -> None:
        """Remove what a failed ezdxf call left in model space (it may add
        the entity before failing)."""
        for e in list(self.msp)[count:]:
            try:
                self.msp.delete_entity(e)
            except Exception:                              # pragma: no cover
                pass

    def _write_radial(self, d: RadialDimension, tr) -> None:
        """RADIUS / DIAMETER dimension. The arrow touches the circle exactly
        where the PDF arrow does; the value shown is the original PDF text,
        along the line or horizontal like in the PDF."""
        before = len(self.msp)
        try:
            c, tip = tr.pt(d.center), tr.pt(d.tip)
            dd = math.dist(c, tip)
            r = tr.length(d.radius)
            if dd < 1e-9 or r < 1e-9:
                return
            u = ((tip[0] - c[0]) / dd, (tip[1] - c[1]) / dd)
            override = self._dim_override(d.height, tr)
            # value written along the line, or horizontal (with a landing
            # when outside)
            line_ang = math.degrees(math.atan2(u[1], u[0]))
            aligned = angle_diff_mod180(line_ang, d.text_rotation) <= 10.0
            override["dimtih"] = override["dimtoh"] = 0 if aligned else 1
            # ezdxf: the dimension line runs from the centre through
            # `location` -> put it ON the PDF line, where the value (or the
            # corner before a horizontal landing) is
            ref = d.kink if d.kink is not None and not aligned \
                else d.text_center
            s = None
            if ref is not None:
                p = tr.pt(ref)
                s = (p[0] - c[0]) * u[0] + (p[1] - c[1]) * u[1]
                if d.kind == "radius" and s < 0.25 * r:
                    s = None                   # value at the centre: default
                elif d.kind == "diameter" and abs(s) < 1e-3 * r:
                    s = 1e-3 * r               # value at the centre
            add = (self.msp.add_radius_dim if d.kind == "radius"
                   else self.msp.add_diameter_dim)
            common = dict(text=d.text, dimstyle="Standard", override=override,
                          dxfattribs={"layer": LAYER_DIM})
            if s is not None:
                dim = add(center=c, radius=r,
                          location=(c[0] + u[0] * s, c[1] + u[1] * s),
                          **common)
            else:
                dim = add(center=c, mpoint=(c[0] + u[0] * r, c[1] + u[1] * r),
                          **common)
            dim.render()
            self.stats.dimensions += 1
            self._count(LAYER_DIM)
        except Exception as exc:
            self._undo_from(before)
            self._warn_once("dim", f"Some dimensions fell back: {exc}")

    def _write_angular(self, d: AngularDimension, tr) -> None:
        """ANGLE (3-point angular) or ARC LENGTH dimension on the PDF arc.
        Its extension lines are not drawn: the PDF ones stay as geometry.
        ARC_DIMENSION exists from AutoCAD 2007 (and not in LibreDWG): for
        older versions and DWG it is written as its drawing (lines, arc,
        arrows, text) on layer DIM."""
        before = len(self.msp)
        try:
            cx, cy = d.center
            sweep = d.sweep

            def at(a: float, rad: float):
                return tr.pt((cx + rad * math.cos(math.radians(a)),
                              cy + rad * math.sin(math.radians(a))))
            rad = d.radius if d.kind == "angle" else (d.arc_radius or d.radius)
            override = self._dim_override(d.height, tr)
            override["dimse1"] = override["dimse2"] = 1
            # the y flip reverses the angles: the DXF angle goes from the
            # PDF end point to the PDF start point (counter-clockwise)
            args = dict(base=at(d.start_angle + sweep / 2.0, d.radius),
                        center=tr.pt(d.center), p1=at(d.end_angle, rad),
                        p2=at(d.start_angle, rad),
                        location=(tr.pt(d.text_center)
                                  if d.text_center is not None else None),
                        text=d.text, text_rotation=d.text_rotation,
                        dimstyle="Standard", override=override,
                        dxfattribs={"layer": LAYER_DIM})
            if d.kind == "angle":
                dim = self.msp.add_angular_dim_3p(**args)
                dim.render()
            else:
                dim = self.msp.add_arc_dim_3p(**args)
                dim.render()
                if self.s.dxf_version in ("R12", "R2000", "R2004"):
                    self._explode_dimension(dim.dimension)
            self.stats.dimensions += 1
            self._count(LAYER_DIM)
        except Exception as exc:
            self._undo_from(before)
            self._warn_once("dim", f"Some dimensions fell back: {exc}")

    def _explode_dimension(self, dim) -> None:
        """Replace a rendered dimension by its drawing, on layer DIM."""
        block = dim.dxf.get("geometry", "")
        for e in dim.explode():
            if e.dxftype() == "POINT":                 # definition points
                self.msp.delete_entity(e)
            else:
                e.dxf.layer = LAYER_DIM
        if block and block in self.doc.blocks:
            try:
                self.doc.blocks.delete_block(block, safe=False)
            except Exception:                              # pragma: no cover
                pass

    def _write_leader(self, ld: LeaderEntity, tr) -> None:
        """MULTILEADER (R2007+) or classic LEADER + text. Multi-line notes
        (tag above the landing, "(HOLD 18)" below...) stay one paragraph."""
        verts = [tr.pt(p) for p in ld.vertices]
        lines = ld.lines or [ld.text]
        top = lines[0]
        h = self._text_height(top, tr)
        a = math.radians(top.rotation)
        up = (-math.sin(a), -math.cos(a))                   # page coords
        cap = top.height * self.s.text_height_factor
        corner = tr.pt((top.origin[0] + up[0] * cap,       # top-left of
                        top.origin[1] + up[1] * cap))      # the note
        content = "\\P".join(t.text for t in lines)
        modern = self.s.dxf_version not in ("R12", "R2000", "R2004")
        try:
            if modern:
                from ezdxf.render import mleader
                b = self.msp.add_multileader_mtext("Standard")
                b.set_content(content, char_height=h,
                              alignment=mleader.TextAlignment.left,
                              style=TEXT_STYLE)
                # A horizontal last segment is the PDF "landing" (the line
                # the note is written on): it becomes the MLEADER dogleg and
                # the note is underlined by it, exactly like the PDF.
                pts = list(verts)
                width = max(tr.length(t.width or 0.55 * t.height * len(t.text))
                            for t in lines)
                landing = len(pts) >= 2 and abs(pts[-1][1] - pts[-2][1]) \
                    <= 1e-3 * max(abs(pts[-1][0] - pts[-2][0]), 1e-9)
                if landing:
                    shaft = pts[-2]
                    pts = pts[:-1] if len(pts) >= 3 else pts
                    left = corner[0] >= shaft[0] - width / 2
                    edge = corner[0] if left else corner[0] + width
                    dogleg = max(abs(edge - shaft[0]), h * 0.2)
                    joint = mleader.HorizontalConnection.\
                        bottom_of_top_line_underline
                else:
                    left = corner[0] >= pts[-1][0]
                    dogleg = h * 0.6
                    joint = mleader.HorizontalConnection.middle_of_top_line
                # sizes in drawing units (the style defaults are tiny)
                b.set_arrow_properties(size=h * 0.9)
                b.set_connection_properties(landing_gap=h * 0.15,
                                            dogleg_length=dogleg)
                b.set_connection_types(left=joint, right=joint)
                side = (mleader.ConnectionSide.left if left
                        else mleader.ConnectionSide.right)
                b.add_leader_line(side, [Vec2(p) for p in pts])
                b.build(insert=Vec2(corner))
                b.multileader.dxf.layer = LAYER_LEADER
                b.multileader.dxf.color = 256
            elif not self.r12:
                self.msp.add_leader(vertices=verts,
                                    dxfattribs={"layer": LAYER_LEADER})
                if len(lines) > 1:
                    mt = self.msp.add_mtext(content, dxfattribs={
                        "layer": LAYER_LEADER, "char_height": h,
                        "style": TEXT_STYLE, "rotation": top.rotation})
                    mt.set_location(corner, attachment_point=1)
                else:
                    txt = self.msp.add_text(top.text, dxfattribs={
                        "layer": LAYER_LEADER, "height": h,
                        "style": TEXT_STYLE, "rotation": top.rotation})
                    txt.set_placement(tr.pt(top.origin))
            else:
                self.msp.add_polyline2d(verts, dxfattribs={
                    "layer": LAYER_LEADER})
                for t in lines:
                    txt = self.msp.add_text(t.text, dxfattribs={
                        "layer": LAYER_LEADER, "height": h,
                        "rotation": t.rotation})
                    txt.set_placement(tr.pt(t.origin))
            self.stats.leaders += 1
            self._count(LAYER_LEADER)
        except Exception as exc:
            self._warn_once("leader", f"Some leaders fell back: {exc}")

    # ---- blocks -------------------------------------------------------------------
    def write_blocks(self, br: BlockResult, tr) -> None:
        if not br.definitions:
            return
        self._role_layer(LAYER_BLOCKS)
        for k, definition in enumerate(br.definitions):
            self._block_counter += 1
            name = f"CC_SYMBOL_{self._block_counter:03d}"
            blk = self.doc.blocks.new(name=name)
            local = _LocalTransform(tr, definition.centroid)
            # block content keeps its ORIGINAL style layers (faithful look;
            # freezing a style layer also hides it inside every block)
            for pl in definition.polylines:
                self._write_polyline(pl, local, self._layer_of(pl.style),
                                     target=blk, count=False)
            for a in definition.arcs:
                self._write_arc(a, local, self._layer_of(a.style),
                                target=blk, count=False)
            for c in definition.circles:
                self._write_circle(c, local, self._layer_of(c.style),
                                   target=blk, count=False)
            for s in definition.splines:
                self._write_spline(s, local, self._layer_of(s.style),
                                   target=blk, count=False)
            for e in blk:                       # per-layer count for the report
                lay = e.dxf.layer
                self.stats.block_layer_counts[lay] = \
                    self.stats.block_layer_counts.get(lay, 0) + 1
            for ins in br.inserts[k]:
                att = {"layer": LAYER_BLOCKS}
                pos, rot, mirror = _insert_parts(ins)
                if rot:
                    att["rotation"] = rot
                if mirror:
                    att["xscale"] = -1.0
                self.msp.add_blockref(name, insert=tr.pt(pos),
                                      dxfattribs=att)
                self.stats.blocks_inserted += 1
                self._count(LAYER_BLOCKS)
            self.stats.blocks_defined += 1
            self.stats.block_report.append(
                f"{name}: {definition.entity_count()} entities x "
                f"{len(br.inserts[k])} insertions")

    # ---- save --------------------------------------------------------------------
    def save(self, path: str) -> None:
        self.doc.saveas(path)


def _image_corner(m, tr, x: float, y: float):
    """Corner (x, y) of the image unit square, in DXF coordinates."""
    a, b, c, d, e, f = m
    return tr.pt((a * x + c * y + e, b * x + d * y + f))


def _insert_parts(ins):
    """An insertion is a point, or (point, rotation_deg, mirror)."""
    if len(ins) == 3 and isinstance(ins[0], (tuple, list)):
        return ins[0], float(ins[1]), bool(ins[2])
    return ins, 0.0, False


class _LocalTransform:
    """Page transform with the origin moved to a block's insertion point."""

    def __init__(self, tr: Transform, centroid):
        self.tr = tr
        self.origin = tr.pt(centroid)

    def pt(self, p):
        g = self.tr.pt(p)
        return (g[0] - self.origin[0], g[1] - self.origin[1])

    def length(self, v):
        return self.tr.length(v)

    def arc_angles(self, s, e):
        return self.tr.arc_angles(s, e)


def _signed_offset(p1, p2, lp) -> float:
    """Signed distance of lp from the line p1-p2 (controls dim line side)."""
    L = math.dist(p1, p2)
    if L < 1e-12:
        return 1.0
    return ((p2[0] - p1[0]) * (lp[1] - p1[1])
            - (p2[1] - p1[1]) * (lp[0] - p1[0])) / L


# ---------------------------------------------------------------------------
# MTEXT grouping
# ---------------------------------------------------------------------------
def group_text_lines(texts: List[RawText]) -> List[List[RawText]]:
    """
    Group text spans into paragraphs (-> MTEXT). Lines join when they share
    colour and size, start at the same x (left-aligned) and are stacked
    0.6 to 2.2 line heights apart. Every input span appears in exactly one
    group (single spans stay TEXT). Rotated text is grouped along its own
    direction. O(n log n).
    """
    buckets: Dict[tuple, List[RawText]] = {}
    for t in texts:
        size_class = round(math.log(max(t.height, 0.1)) / math.log(1.12))
        buckets.setdefault((t.color, size_class, round(t.rotation)), []
                           ).append(t)
    groups: List[List[RawText]] = []
    for (_, _, rot), items in buckets.items():
        a = math.radians(rot)
        d = (math.cos(a), -math.sin(a))             # reading dir (page)
        n = (math.sin(a), math.cos(a))              # 'down' dir (page)
        along = lambda t: t.origin[0] * d[0] + t.origin[1] * d[1]   # noqa
        down = lambda t: t.origin[0] * n[0] + t.origin[1] * n[1]    # noqa
        items.sort(key=along)
        # columns of left-aligned spans
        columns: List[List[RawText]] = []
        for t in items:
            if columns and along(t) - along(columns[-1][0]) \
                    <= 0.6 * columns[-1][0].height:
                columns[-1].append(t)
            else:
                columns.append([t])
        for col in columns:
            col.sort(key=down)
            run = [col[0]]
            for t in col[1:]:
                gap = down(t) - down(run[-1])
                h = run[-1].height
                if 0.6 * h <= gap <= 2.2 * h:
                    run.append(t)
                else:
                    groups.append(run)
                    run = [t]
            groups.append(run)
    return groups
