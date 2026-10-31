"""
extractor.py — STEP 1: read one PDF page and produce RAW primitives.

Uses PyMuPDF. Nothing is interpreted here: a circle drawn in the PDF arrives
as 4 Bezier curves; interpretation happens later in geometry.py.

All coordinates are returned in DISPLAYED page coordinates (points, origin
top-left, y pointing DOWN) — i.e. already corrected for the page /Rotate
attribute, so the DXF matches what the user sees in any PDF viewer.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .compat import page_matrix, pymupdf, transform_point, transform_vector

Point = Tuple[float, float]          # page coordinates (y grows DOWNWARD)
RGB = Tuple[int, int, int]           # 0-255 per channel
BACKGROUND_SHARE = 0.85              # a fill covering this share of the
                                     # sheet is the page background


# ---------------------------------------------------------------------------
# Raw primitive dataclasses — the common language of the whole pipeline
# ---------------------------------------------------------------------------
@dataclass
class Style:
    """Stroke style shared by raw geometry primitives."""
    color: RGB = (0, 0, 0)
    width: float = 0.0               # stroke width in PDF points
    dashed: bool = False
    dash_pattern: str = ""           # raw PDF dash string, e.g. "[ 3 3 ] 0"
    linetype: str = "CONTINUOUS"     # DASHED / DASHDOT / CENTER / PHANTOM ...
    pdf_layer: str = ""              # native PDF (OCG) layer name, if any


@dataclass
class RawSegment:
    p1: Point
    p2: Point
    style: Style


@dataclass
class RawBezier:
    """Cubic Bezier: p0 start, p1/p2 control points, p3 end."""
    p0: Point
    p1: Point
    p2: Point
    p3: Point
    style: Style


@dataclass
class RawFill:
    """A filled path (candidate HATCH or arrowhead). Polygon in page coords."""
    points: List[Point]
    color: RGB
    pdf_layer: str = ""
    # the page background (a fill covering most of the sheet). Decided when
    # the page is read, because cutting the page to a selected area makes
    # it as small as the area (it would then look like a normal fill)
    background: bool = False

    @property
    def area(self) -> float:
        pts = self.points
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0


@dataclass
class RawText:
    text: str
    origin: Point                    # baseline origin, page coords
    height: float                    # font size in PDF points
    rotation: float                  # degrees, CCW, DXF convention (y up)
    color: RGB = (0, 0, 0)
    font: str = ""
    pdf_layer: str = ""
    source: str = "pdf"              # "pdf" | "ocr" | "shx"
    width: float = 0.0               # advance length along the text direction
    cap_height: float = 0.0          # measured letter height (pt), when known
                                     # exactly (SHX text): used as is instead
                                     # of height x text height ratio
    flags: int = 0                   # PyMuPDF span flags (2 italic, 16 bold)

    def direction(self) -> Point:
        """Unit reading direction in PAGE coordinates (y down)."""
        a = math.radians(self.rotation)
        return (math.cos(a), -math.sin(a))

    def center(self) -> Point:
        """Approximate visual centre of the text (page coordinates)."""
        a = math.radians(self.rotation)
        dx, dy = math.cos(a), -math.sin(a)          # reading direction
        ux, uy = -math.sin(a), -math.cos(a)         # 'up' direction
        w = self.width or 0.55 * self.height * len(self.text)
        cap = 0.35 * self.height
        return (self.origin[0] + dx * w / 2 + ux * cap,
                self.origin[1] + dy * w / 2 + uy * cap)


@dataclass
class RawImage:
    bbox: Tuple[float, float, float, float]   # x0, y0, x1, y1 page coords
    png_bytes: bytes                           # extracted image as PNG
    index: int
    width_px: int = 0
    height_px: int = 0
    # image space (unit square, row 0 at the top) -> displayed page coords;
    # carries the rotation / mirroring of the image and of the page
    matrix: Tuple[float, ...] = ()


@dataclass
class PageData:
    """Everything extracted from one PDF page."""
    number: int                      # 1-based page number
    width: float                     # displayed page width in PDF points
    height: float                    # displayed page height in PDF points
    rotation: int = 0                # /Rotate attribute of the page
    segments: List[RawSegment] = field(default_factory=list)
    beziers: List[RawBezier] = field(default_factory=list)
    fills: List[RawFill] = field(default_factory=list)
    texts: List[RawText] = field(default_factory=list)
    shx_texts: List[RawText] = field(default_factory=list)
    images: List[RawImage] = field(default_factory=list)
    pdf_layers: List[str] = field(default_factory=list)  # OCG names found
    warnings: List[str] = field(default_factory=list)
    text_outlines: int = 0           # glyph outlines replaced by real text

    @property
    def vector_count(self) -> int:
        return len(self.segments) + len(self.beziers) + len(self.fills)

    @property
    def image_coverage(self) -> float:
        """Fraction of the page area covered by raster images (0..1)."""
        area = max(self.width * self.height, 1e-9)
        cov = 0.0
        for im in self.images:
            x0, y0, x1, y1 = im.bbox
            x0, y0 = max(x0, 0.0), max(y0, 0.0)
            x1, y1 = min(x1, self.width), min(y1, self.height)
            if x1 > x0 and y1 > y0:
                cov += (x1 - x0) * (y1 - y0)
        return min(cov / area, 1.0)

    @property
    def kind(self) -> str:
        """'vector', 'scanned' or 'empty' — drives the conversion strategy."""
        return classify(self.vector_count, self.image_coverage,
                        len(self.texts))

    @property
    def is_vector(self) -> bool:
        return self.kind == "vector"


def classify(vector_count: int, image_coverage: float, text_count: int) -> str:
    """Page classification rule (shared with inspect.py).

    * scanned : a raster image covers most of the page and there are few
                vectors (a scanned plan, maybe with a stamp or frame added)
    * empty   : nothing meaningful at all
    * vector  : everything else (the ideal case)
    """
    if image_coverage >= 0.5 and vector_count < 500:
        return "scanned"
    if vector_count < 5 and image_coverage < 0.05 and text_count == 0:
        return "empty"
    if vector_count < 5 and image_coverage >= 0.05:
        return "scanned"
    return "vector"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_rgb(color) -> RGB:
    """PyMuPDF colors are float tuples 0..1 (or None). Normalize to 0-255."""
    if color is None:
        return (0, 0, 0)
    try:
        if len(color) == 1:                      # gray
            g = max(0, min(255, int(round(color[0] * 255))))
            return (g, g, g)
        if len(color) == 4:                      # CMYK -> RGB (simple)
            c, m, y, k = color
            return tuple(max(0, min(255, int(round(255 * (1 - v) * (1 - k)))))
                         for v in (c, m, y))
        return tuple(max(0, min(255, int(round(c * 255)))) for c in color[:3])
    except (TypeError, IndexError, ValueError):
        return (0, 0, 0)


def _int_to_rgb(value: int) -> RGB:
    """Text spans carry color as a packed sRGB int."""
    value = int(value or 0)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def classify_linetype(dashes: Optional[str]) -> str:
    """
    Map a PDF dash array to a named DXF linetype:
      CONTINUOUS / DASHED / DASHDOT / CENTER / PHANTOM.
    The PDF dash spec looks like '[ on off on off ] phase'. The SHAPE of the
    pattern identifies the linetype: a long dash followed by short dashes is
    the dash-dot family used for axes and centrelines.
    """
    if not dashes:
        return "CONTINUOUS"
    inside = dashes.split("]")[0].replace("[", "").strip()
    if not inside:
        return "CONTINUOUS"
    try:
        vals = [float(x) for x in inside.replace(",", " ").split()]
    except ValueError:
        return "DASHED"
    vals = [v for v in vals if v >= 0]
    if not vals or all(v == 0 for v in vals):
        return "CONTINUOUS"
    on = vals[0::2]
    if len(on) <= 1 or len(set(round(v, 1) for v in on)) == 1:
        return "DASHED"                       # simple on/off dash
    long_d = max(on)
    short_d = min(on) if min(on) > 0 else 0.1
    if long_d / short_d >= 3.0:
        dots = sum(1 for v in on if v <= short_d * 1.6)
        return "PHANTOM" if dots >= 2 else "CENTER"
    return "DASHDOT"


def is_dashed(dashes: Optional[str]) -> bool:
    return classify_linetype(dashes) != "CONTINUOUS"


def _flatten_bezier(pts: List[Point], n: int = 8) -> List[Point]:
    """Sample a cubic Bezier into n+1 points (only for fill outlines)."""
    p0, p1, p2, p3 = pts
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        out.append((mt**3 * p0[0] + 3 * mt**2 * t * p1[0]
                    + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                    mt**3 * p0[1] + 3 * mt**2 * t * p1[1]
                    + 3 * mt * t**2 * p2[1] + t**3 * p3[1]))
    return out


def _extend_outline(outline: List[Point], pts: List[Point]) -> None:
    """Append points, skipping immediate duplicates."""
    for p in pts:
        if not outline or (abs(outline[-1][0] - p[0]) > 1e-9
                           or abs(outline[-1][1] - p[1]) > 1e-9):
            outline.append(p)


def is_autocad_pdf(doc) -> bool:
    """True when the PDF was produced by AutoCAD / an Autodesk plotter."""
    meta = doc.metadata or {}
    blob = " ".join(str(meta.get(k) or "") for k in ("creator", "producer"))
    blob = blob.lower()
    return any(k in blob for k in ("autocad", "autodesk", "dwg to pdf"))


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def extract_page(doc, page_index: int, read_shx_comments: bool = True,
                 text_outlines: bool = True) -> PageData:
    """Extract all raw primitives from one page (0-based index)."""
    page = doc[page_index]
    m = page_matrix(page)

    def P(pt) -> Point:                          # unrotated -> displayed
        return transform_point(m, pt.x, pt.y)

    data = PageData(number=page_index + 1, width=page.rect.width,
                    height=page.rect.height, rotation=page.rotation % 360)
    page_area = data.width * data.height
    layer_names = set()

    # ---- 1. Vector drawings -------------------------------------------------
    try:
        drawings = page.get_drawings()
    except Exception as exc:                                  # corrupt content
        data.warnings.append(
            f"Page {data.number}: drawing extraction failed ({exc})")
        drawings = []

    for path in drawings:
        pdf_layer = path.get("layer") or ""
        if pdf_layer:
            layer_names.add(pdf_layer)
        dashes = path.get("dashes")
        style = Style(color=_to_rgb(path.get("color")),
                      width=float(path.get("width") or 0.0),
                      dashed=is_dashed(dashes),
                      dash_pattern=dashes or "",
                      linetype=classify_linetype(dashes),
                      pdf_layer=pdf_layer)
        ptype = path.get("type") or "s"          # 's'troke, 'f'ill, 'fs' both
        stroked = "s" in ptype
        fill_rgb = (_to_rgb(path.get("fill"))
                    if path.get("fill") is not None and "f" in ptype else None)
        outline: List[Point] = []

        for item in path.get("items", []):
            kind = item[0]
            if kind == "l":                                   # straight line
                p1, p2 = P(item[1]), P(item[2])
                if stroked:
                    data.segments.append(RawSegment(p1, p2, style))
                _extend_outline(outline, [p1, p2])
            elif kind == "c":                                 # cubic Bezier
                pts = [P(p) for p in item[1:5]]
                if stroked:
                    data.beziers.append(RawBezier(*pts, style=style))
                _extend_outline(outline, _flatten_bezier(pts))
            elif kind == "re":                                # rectangle
                r = item[1]
                corners = [P(pymupdf.Point(r.x0, r.y0)),
                           P(pymupdf.Point(r.x1, r.y0)),
                           P(pymupdf.Point(r.x1, r.y1)),
                           P(pymupdf.Point(r.x0, r.y1))]
                if stroked:
                    for i in range(4):
                        data.segments.append(
                            RawSegment(corners[i], corners[(i + 1) % 4], style))
                _extend_outline(outline, corners + [corners[0]])
            elif kind == "qu":                                # quadrilateral
                q = item[1]
                pts = [P(q.ul), P(q.ur), P(q.lr), P(q.ll)]
                if stroked:
                    for i in range(4):
                        data.segments.append(
                            RawSegment(pts[i], pts[(i + 1) % 4], style))
                _extend_outline(outline, pts + [pts[0]])

        if fill_rgb is not None and len(outline) >= 3:
            fill = RawFill(points=outline, color=fill_rgb,
                           pdf_layer=pdf_layer)
            fill.background = fill.area > BACKGROUND_SHARE * page_area
            data.fills.append(fill)

    # ---- 2. Native text ------------------------------------------------------
    try:
        text_dict = page.get_text("dict")
    except Exception as exc:
        data.warnings.append(
            f"Page {data.number}: text extraction failed ({exc})")
        text_dict = {"blocks": []}

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:                            # 0 = text block
            continue
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            dx, dy = transform_vector(m, dx, dy)
            # Page y points down; DXF angles are CCW with y up -> negate dy.
            rotation = math.degrees(math.atan2(-dy, dx))
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if not txt:
                    continue
                ox, oy = span.get("origin", (0.0, 0.0))
                bx0, by0, bx1, by1 = span.get("bbox", (ox, oy, ox, oy))
                bw, bh = abs(bx1 - bx0), abs(by1 - by0)
                ldx, ldy = line.get("dir", (1.0, 0.0))
                adv = abs(bw * ldx) + abs(bh * ldy)       # along the text
                data.texts.append(RawText(
                    text=txt,
                    origin=transform_point(m, ox, oy),
                    height=float(span.get("size", 2.5) or 2.5),
                    rotation=round(rotation, 4),
                    color=_int_to_rgb(span.get("color", 0)),
                    font=span.get("font", "") or "",
                    width=adv,
                    flags=int(span.get("flags", 0) or 0)))

    # ---- 2b. TrueType text drawn as outlines -------------------------------
    # CAD programs often export TrueType text as filled letter outlines and
    # add the same text, INVISIBLE, on top (for searching). The invisible
    # text is the real one: the outlines underneath are left out, so the DXF
    # gets one editable text instead of a text plus a pile of filled shapes.
    if text_outlines:
        try:
            data.text_outlines = _drop_text_outlines(page, m, data)
        except Exception as exc:                              # never fatal
            data.warnings.append(
                f"Page {data.number}: text outlines not checked ({exc})")

    # ---- 3. AutoCAD SHX text comments ---------------------------------------
    # AutoCAD (PDFSHX=1, default) draws SHX text as vector strokes AND adds a
    # hidden comment holding the real string ("AutoCAD SHX Text" Square
    # annotations in recent versions, Text/FreeText in older ones). The
    # strokes inside each box give the exact position and letter height.
    if read_shx_comments:
        try:
            data.shx_texts = _shx_texts(page, m, data,
                                        autocad=is_autocad_pdf(doc))
        except Exception as exc:                              # never fatal
            data.warnings.append(
                f"Page {data.number}: SHX comments not read ({exc})")

    # ---- 4. Embedded raster images ------------------------------------------
    try:
        for idx, info in enumerate(page.get_image_info(xrefs=True)):
            xref = info.get("xref", 0)
            if xref <= 0:
                continue
            pix = pymupdf.Pixmap(doc, xref)
            if pix.colorspace and pix.colorspace.n > 3:       # CMYK -> RGB
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if pix.alpha:                                     # drop alpha
                pix = pymupdf.Pixmap(pix, 0)
            bb = pymupdf.Rect(info["bbox"]) * m               # displayed box
            mat = ()
            if info.get("transform"):
                t = pymupdf.Matrix(info["transform"]) * m      # then rotation
                mat = (t.a, t.b, t.c, t.d, t.e, t.f)
            data.images.append(RawImage(bbox=(bb.x0, bb.y0, bb.x1, bb.y1),
                                        png_bytes=pix.tobytes("png"),
                                        index=idx, width_px=pix.width,
                                        height_px=pix.height, matrix=mat))
    except Exception as exc:
        data.warnings.append(
            f"Page {data.number}: image extraction failed ({exc})")

    data.pdf_layers = sorted(layer_names)
    return data


# ---------------------------------------------------------------------------
# AutoCAD SHX text
# ---------------------------------------------------------------------------
SHX_TITLE = "AutoCAD SHX Text"
SHX_TYPES = ("Text", "FreeText", "Square")
SHX_PADDING = 3.0               # AutoCAD's box margin around the letters (pt)
_READ_ONLY = 64                 # PDF annotation flag set by CAD exporters


def _is_shx_annot(annot, info: dict, autocad: bool) -> bool:
    """AutoCAD's SHX comment, NOT a reviewer's markup.

    AutoCAD titles them "AutoCAD SHX Text" (other CAD programs and
    languages: a title containing "SHX"). Without such a title, only an
    invisible (no colour, no border) read-only box in a PDF made by AutoCAD
    is accepted: a visible review comment must never move drawing lines to
    the hidden layer."""
    if "SHX" in (info.get("title") or "").upper():
        return True
    if not autocad:
        return False
    atype = annot.type[1] if annot.type else ""
    if atype not in SHX_TYPES:
        return False
    colors = annot.colors or {}
    border = (annot.border or {}).get("width") or 0
    return (not colors.get("stroke") and not colors.get("fill")
            and border <= 0 and bool(annot.flags & _READ_ONLY))


def _shx_texts(page, m, data: "PageData",
               autocad: bool = True) -> List[RawText]:
    """Real strings of SHX text, placed on their letters.

    Each AutoCAD box holds one text. Its letters are vector strokes already
    extracted (data.segments / data.beziers): their bounding box gives the
    left edge, the baseline and the letter height. Without strokes the box
    minus AutoCAD's margin is used."""
    from .spatial import GridIndex
    annots = []
    for annot in page.annots() or []:
        info = annot.info or {}
        content = (info.get("content") or "").strip()
        if not content or not _is_shx_annot(annot, info, autocad):
            continue
        r = annot.rect * m                       # displayed coordinates
        annots.append((content, r))
    if not annots:
        return []
    from dataclasses import replace

    from .constants import LAYER_SHX_STROKES
    strokes: GridIndex = GridIndex(24.0)
    for k, sg in enumerate(data.segments):
        strokes.insert(("s", k), (min(sg.p1[0], sg.p2[0]),
                                  min(sg.p1[1], sg.p2[1]),
                                  max(sg.p1[0], sg.p2[0]),
                                  max(sg.p1[1], sg.p2[1])))
    for k, bz in enumerate(data.beziers):
        xs = (bz.p0[0], bz.p1[0], bz.p2[0], bz.p3[0])
        ys = (bz.p0[1], bz.p1[1], bz.p2[1], bz.p3[1])
        strokes.insert(("b", k), (min(xs), min(ys), max(xs), max(ys)))
    moved: Dict[int, Style] = {}

    def stroke_style(st: Style) -> Style:
        new = moved.get(id(st))
        if new is None:
            new = moved[id(st)] = replace(st, pdf_layer=LAYER_SHX_STROKES)
        return new

    out: List[RawText] = []
    for content, r in annots:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not lines:
            continue
        # the letters: strokes lying entirely inside the box
        g = 0.6
        pts: List[Point] = []
        for kind, k in strokes.query(r.x0, r.y0, r.x1, r.y1):
            prim = data.segments[k] if kind == "s" else data.beziers[k]
            ctrl = (prim.p1, prim.p2) if kind == "s" else \
                (prim.p0, prim.p1, prim.p2, prim.p3)
            if all(r.x0 - g <= p[0] <= r.x1 + g and r.y0 - g <= p[1] <= r.y1 + g
                   for p in ctrl):
                pts.extend(ctrl)
                prim.style = stroke_style(prim.style)
        if len(pts) >= 2:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            pad = min(SHX_PADDING, r.width / 4, r.height / 4)
            x0, y0, x1, y1 = r.x0 + pad, r.y0 + pad, r.x1 - pad, r.y1 - pad
        w, h = max(x1 - x0, 0.1), max(y1 - y0, 0.1)
        vertical = h > 1.5 * w and len(lines[0]) > 1
        n = len(lines)
        if not vertical:
            line_h = h / (n + 0.6 * (n - 1))       # letters + 60 % line gap
            for k, txt in enumerate(lines):
                base = y0 + line_h + k * 1.6 * line_h
                out.append(RawText(text=txt, origin=(x0, base),
                                   height=line_h / 0.7, rotation=0.0,
                                   source="shx", width=w, cap_height=line_h))
        else:                                       # reads bottom to top
            line_h = w / (n + 0.6 * (n - 1))
            for k, txt in enumerate(lines):
                base = x0 + line_h + k * 1.6 * line_h
                out.append(RawText(text=txt, origin=(base, y1),
                                   height=line_h / 0.7, rotation=90.0,
                                   source="shx", width=h, cap_height=line_h))
    return out


# ---------------------------------------------------------------------------
# TrueType text drawn as outlines + invisible text
# ---------------------------------------------------------------------------
def _drop_text_outlines(page, m, data: "PageData") -> int:
    """Remove the filled letter outlines lying under INVISIBLE text spans
    (text render mode 3). Returns how many outlines were removed."""
    boxes = []
    for span in page.get_texttrace():
        if span.get("type") != 3 or not span.get("chars"):
            continue
        r = pymupdf.Rect(span["bbox"]) * m
        if r.is_empty:
            continue
        # The drawn letters use the real font, the invisible copy a standard
        # one: they start together but the drawn text often runs longer.
        # The box is extended at the END of the reading direction.
        dx, dy = transform_vector(m, *(span.get("dir") or (1.0, 0.0)))
        h = min(r.width, r.height)
        long_ = max(r.width, r.height)
        g, run = 0.2 * h, 0.75 * long_ + 0.5 * h
        x0, y0, x1, y1 = r.x0 - g, r.y0 - g, r.x1 + g, r.y1 + g
        if abs(dx) >= abs(dy):
            x0, x1 = (x0, x1 + run) if dx >= 0 else (x0 - run, x1)
        else:
            y0, y1 = (y0 - run, y1) if dy < 0 else (y0, y1 + run)
        boxes.append((x0, y0, x1, y1))
    if not boxes or not data.fills:
        return 0
    from .spatial import GridIndex
    index: GridIndex = GridIndex(24.0)
    for b in boxes:
        index.insert(b, b)
    keep, removed = [], 0
    for f in data.fills:
        xs = [p[0] for p in f.points]
        ys = [p[1] for p in f.points]
        fx0, fy0, fx1, fy1 = min(xs), min(ys), max(xs), max(ys)
        inside = any(b[0] <= fx0 and fx1 <= b[2] and b[1] <= fy0 and fy1 <= b[3]
                     for b in index.query(fx0, fy0, fx1, fy1))
        if inside:
            removed += 1
        else:
            keep.append(f)
    data.fills = keep
    return removed
