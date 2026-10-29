"""
raster.py — vectorization + OCR for SCANNED (raster) PDF pages.

The page is rendered at high resolution, then converted into the SAME raw
dataclasses as extractor.py (RawSegment / RawText), so the whole downstream
pipeline (chaining, layers, dimensions, blocks, DXF writing) works unchanged
on scanned drawings.

Steps:
  1. render the page in grayscale (default 300 dpi, capped for huge sheets)
  2. OCR (optional) with the PP-OCR models (see ocr.py): text lines at any
     angle; recognised lines are masked so letters are not traced as
     geometry
  3. adaptive binarization + despeckle
  4. circles (Hough, validated against the real ink) -> CIRCLE entities
  5. straight lines (probabilistic Hough) -> merged collinear segments

HONESTY BY DESIGN: tracing is approximate. Traced content goes to TRACE_*
layers and the original scan stays underneath on the locked IMG_RASTER layer
so every traced entity can be checked against the source.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from .constants import LAYER_TRACE, MAX_RASTER_PIXELS
from .extractor import PageData, RawSegment, RawText, Style

try:                                              # hard dependency for tracing
    import cv2
    HAS_CV2 = True
except ImportError:                               # pragma: no cover
    HAS_CV2 = False

from . import ocr as ocr_engines


class RTol:
    """Raster tracing tuning (pixels at the working resolution)."""
    BIN_BLOCK = 35           # adaptive threshold block size (odd)
    BIN_C = 11               # adaptive threshold constant
    HOUGH_THRESH = 30        # min votes for a line
    HOUGH_MIN_LEN = 18       # min line length (px)
    HOUGH_MAX_GAP = 4        # max gap bridged inside a line (px)
    CIRCLE_MIN_R = 8         # Hough circle radius range (px)
    CIRCLE_MAX_R = 400
    CIRCLE_COVER = 0.70      # fraction of the perimeter that must carry ink
    OCR_MIN_CONF = 55        # OCR confidence threshold (0-100)
    OCR_MIN_H = 6            # min text box height (px)
    OCR_DPI = 150            # resolution the OCR reads the page at: PP-OCR
                             # reads 1.8-3.5 mm drawing text best at about
                             # 120-150 dpi (measured on an A1 sheet: same
                             # result at 200 dpi, twice as slow)...
    OCR_MIN_SIDE = 2000      # ...but small sheets keep at least 2000 px on
                             # their long side (finer for tiny A4/A3 text)
    MERGE_ANGLE = 1.5        # collinear merge: max angle difference (deg)
    MERGE_OFFSET = 0.6       # ...max perpendicular offset (page points)
    MERGE_GAP = 1.5          # ...max gap between pieces (page points)


@dataclass
class RasterCircle:
    center: Tuple[float, float]      # page points
    radius: float


@dataclass
class RasterResult:
    segments: List[RawSegment] = field(default_factory=list)
    texts: List[RawText] = field(default_factory=list)
    circles: List[RasterCircle] = field(default_factory=list)
    dpi_used: int = 0
    ocr_used: bool = False
    ocr_model: str = ""                  # models actually used (report)
    warnings: List[str] = field(default_factory=list)


def _perimeter_coverage(binary: np.ndarray, cx: float, cy: float,
                        r: float, samples: int = 72) -> float:
    """Fraction of circle points that fall on ink (1-px neighbourhood)."""
    h, w = binary.shape
    hits = 0
    for k in range(samples):
        a = 2.0 * math.pi * k / samples
        x = int(round(cx + r * math.cos(a)))
        y = int(round(cy + r * math.sin(a)))
        if 1 <= x < w - 1 and 1 <= y < h - 1 and \
                binary[y - 1:y + 2, x - 1:x + 2].any():
            hits += 1
    return hits / samples


def merge_collinear(segs: List[Tuple[float, float, float, float]]
                    ) -> List[Tuple[float, float, float, float]]:
    """Merge overlapping / touching collinear segments (page points).
    Hough returns several fragments per drawn line (and both edges of thick
    strokes); this collapses them into clean single lines."""
    lines = []
    for x1, y1, x2, y2 in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-6:
            continue
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
        lines.append((ang, x1, y1, x2, y2))
    # bucket by angle, then by perpendicular offset
    buckets: Dict[Tuple[int, int], List[tuple]] = {}
    for ang, x1, y1, x2, y2 in lines:
        a = math.radians(ang)
        off = -math.sin(a) * x1 + math.cos(a) * y1
        key = (int(round(ang / RTol.MERGE_ANGLE)) % int(180 / RTol.MERGE_ANGLE),
               int(round(off / (RTol.MERGE_OFFSET * 2))))
        buckets.setdefault(key, []).append((ang, x1, y1, x2, y2))
    out = []
    for group in buckets.values():
        # mean direction of LINES (mod 180): average the doubled angles
        c2 = sum(math.cos(math.radians(2 * g[0])) for g in group)
        s2 = sum(math.sin(math.radians(2 * g[0])) for g in group)
        a = math.atan2(s2, c2) / 2.0
        u = (math.cos(a), math.sin(a))
        n = (-math.sin(a), math.cos(a))
        offs = [n[0] * g[1] + n[1] * g[2] for g in group]
        off = sum(offs) / len(offs)
        ivals = sorted((min(u[0] * g[1] + u[1] * g[2], u[0] * g[3] + u[1] * g[4]),
                        max(u[0] * g[1] + u[1] * g[2], u[0] * g[3] + u[1] * g[4]))
                       for g in group)
        merged = [list(ivals[0])]
        for s, e in ivals[1:]:
            if s <= merged[-1][1] + RTol.MERGE_GAP:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        for s, e in merged:
            out.append((u[0] * s + n[0] * off, u[1] * s + n[1] * off,
                        u[0] * e + n[0] * off, u[1] * e + n[1] * off))
    return out


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def vectorize_page(doc, page_index: int, dpi: int = 300, ocr: bool = True,
                   ocr_lang: str = "latin",
                   ocr_quality: str = "standard") -> RasterResult:
    """Trace a scanned page. Coordinates returned in page points (y down)."""
    from .compat import pymupdf
    res = RasterResult()
    if not HAS_CV2:                                       # pragma: no cover
        res.warnings.append("Raster tracing unavailable: OpenCV missing.")
        return res
    page = doc[page_index]
    # Safety cap: an A0 sheet at 600 dpi is ~560 Mpx; reduce if needed.
    w_pt, h_pt = page.rect.width, page.rect.height
    max_dpi = int(72.0 * math.sqrt(MAX_RASTER_PIXELS / max(w_pt * h_pt, 1)))
    if dpi > max_dpi:
        res.warnings.append(f"Page {page_index + 1}: scan resolution reduced "
                            f"from {dpi} to {max_dpi} dpi (sheet too large).")
        dpi = max_dpi
    res.dpi_used = dpi
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                          colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.stride)[:, :pix.width].copy()

    # ---- 1. OCR first, then mask the text out of the geometry image --------
    work = img.copy()
    if ocr:
        plan, note = ocr_engines.make_plan(ocr_lang, ocr_quality)
        if note:
            res.warnings.append(f"Page {page_index + 1}: {note}")
        if plan is None:
            texts, boxes, warn = [], [], "OCR skipped."
        else:
            res.ocr_model = plan.description
            texts, boxes, warn = _run_ocr(img, zoom, plan)
        res.texts, res.ocr_used = texts, not warn
        if warn and plan is not None:
            res.warnings.append(warn)
        for (x, y, w, h) in boxes:
            cv2.rectangle(work, (x - 2, y - 2), (x + w + 2, y + h + 2), 255, -1)

    # ---- 2. Binarize (dark strokes on light paper) --------------------------
    binary = cv2.adaptiveThreshold(work, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV,
                                   RTol.BIN_BLOCK, RTol.BIN_C)
    binary = cv2.medianBlur(binary, 3)

    # ---- 3. Circles before lines (holes/bolts must not become polygons) -----
    circles = cv2.HoughCircles(work, cv2.HOUGH_GRADIENT, dp=1.2,
                               minDist=RTol.CIRCLE_MIN_R * 2,
                               param1=120, param2=60,
                               minRadius=RTol.CIRCLE_MIN_R,
                               maxRadius=RTol.CIRCLE_MAX_R)
    if circles is not None:
        mask = np.zeros_like(binary)
        # OpenCV 4 returns (1, N, 3), OpenCV 5 may return (N, 3): normalise
        for cx, cy, r in np.asarray(circles, dtype=float).reshape(-1, 3):
            if _perimeter_coverage(binary, cx, cy, r) < RTol.CIRCLE_COVER:
                continue
            res.circles.append(RasterCircle(center=(cx / zoom, cy / zoom),
                                            radius=r / zoom))
            cv2.circle(mask, (int(cx), int(cy)), int(r), 255, thickness=7)
        if res.circles:
            binary = cv2.bitwise_and(binary, cv2.bitwise_not(mask))

    # ---- 4. Straight lines, then merge the fragments ------------------------
    lines = cv2.HoughLinesP(binary, rho=1, theta=math.pi / 360.0,
                            threshold=RTol.HOUGH_THRESH,
                            minLineLength=RTol.HOUGH_MIN_LEN,
                            maxLineGap=RTol.HOUGH_MAX_GAP)
    style = Style(color=(0, 0, 0), width=0.4, pdf_layer=LAYER_TRACE)
    if lines is not None:
        raw = [(x1 / zoom, y1 / zoom, x2 / zoom, y2 / zoom)
               for (x1, y1, x2, y2) in
               np.asarray(lines, dtype=float).reshape(-1, 4)]
        for x1, y1, x2, y2 in merge_collinear(raw):
            res.segments.append(RawSegment((x1, y1), (x2, y2), style))
    if not res.segments and not res.circles:
        res.warnings.append(f"Page {page_index + 1}: raster tracing found no "
                            "recognisable geometry (very light scan?).")
    return res


def _run_ocr(img: np.ndarray, zoom: float, plan):
    """OCR an image -> (texts, boxes in image px, warning or None). The
    PP-OCR models return whole text lines; a line found vertical (reading
    bottom-to-top) becomes a text rotated by 90 degrees.

    The page is read at RTol.OCR_DPI (small sheets: at least OCR_MIN_SIDE
    pixels): a finer image is reduced first, for speed. Before 1.1 the OCR
    shrank every page to 2000 pixels, so the small text of large sheets was
    lost (an A1 sheet now reads about twice as many labels)."""
    scale = min(1.0, max(RTol.OCR_DPI / (zoom * 72.0),
                         RTol.OCR_MIN_SIDE / max(img.shape[:2])))
    if scale > 0.99:
        small, scale = img, 1.0
    else:
        small = cv2.resize(img, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
        scale = small.shape[1] / img.shape[1]          # exact factor
    try:
        words = ocr_engines.recognize(small, plan)
    except Exception as exc:
        return [], [], f"OCR failed: {exc}"
    texts, boxes = [], []
    for wd in words:
        word, conf = wd.text, wd.conf
        x, y, w, h = (int(round(v / scale)) for v in wd.box)  # image px
        thickness = w if wd.vertical else h
        if not word or conf < RTol.OCR_MIN_CONF or thickness < RTol.OCR_MIN_H:
            continue
        # drop symbol noise (crosses, bubbles, hatching read as | / x] ...)
        alnum = sum(ch.isalnum() for ch in word)
        if alnum == 0 or alnum / max(len(word.replace(" ", "")), 1) < 0.6:
            continue
        if len(word) <= 2 and conf < 80:
            continue
        boxes.append((x, y, w, h))
        if not wd.vertical:
            texts.append(RawText(text=word, origin=(x / zoom, (y + h) / zoom),
                                 height=(h / zoom) / 0.95, rotation=0.0,
                                 font="OCR", source="ocr", width=w / zoom))
        else:                     # reads bottom-to-top, baseline on the right
            texts.append(RawText(text=word, origin=((x + w) / zoom,
                                                    (y + h) / zoom),
                                 height=(w / zoom) / 0.95, rotation=90.0,
                                 font="OCR", source="ocr", width=h / zoom))
    return texts, boxes, None


def merge_into_page(page_data: PageData, res: RasterResult) -> None:
    """Inject traced primitives into the normal pipeline structures."""
    page_data.segments.extend(res.segments)
    page_data.texts.extend(res.texts)
    page_data.warnings.extend(res.warnings)
