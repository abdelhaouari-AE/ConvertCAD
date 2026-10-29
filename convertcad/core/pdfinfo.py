"""
pdfinfo.py — fast look at a PDF BEFORE converting it.

Used by the interface to fill the page panel (thumbnail badges VECTOR /
SCAN / EMPTY, paper size, rotation) and to warn early (password, AutoCAD
SHX comments...). Uses PyMuPDF's fast C-level path listing, so even an A0
sheet with 35 000 primitives is classified in a fraction of a second.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .compat import pymupdf
from .extractor import classify, is_autocad_pdf

# ISO 216 A-series sizes in millimetres (portrait)
_ISO = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594),
        "A3": (297, 420), "A4": (210, 297), "A5": (148, 210),
        "A6": (105, 148)}
PT_TO_MM = 25.4 / 72.0


@dataclass
class PageInfo:
    number: int                       # 1-based
    width_pt: float
    height_pt: float
    rotation: int = 0
    kind: str = "vector"              # vector | scanned | empty
    vector_count: int = 0
    text_count: int = 0
    image_coverage: float = 0.0
    paper: str = ""

    @property
    def width_mm(self) -> float:
        return self.width_pt * PT_TO_MM

    @property
    def height_mm(self) -> float:
        return self.height_pt * PT_TO_MM


@dataclass
class DocumentInfo:
    path: str
    page_count: int = 0
    title: str = ""
    creator: str = ""
    producer: str = ""
    is_autocad: bool = False
    encrypted: bool = False
    ocg_layers: List[str] = field(default_factory=list)
    pages: List[PageInfo] = field(default_factory=list)
    error: str = ""

    @property
    def file_size_mb(self) -> float:
        try:
            return os.path.getsize(self.path) / 1_048_576
        except OSError:
            return 0.0


def paper_size_name(w_pt: float, h_pt: float) -> str:
    """'A3 landscape', 'A1 portrait' or '420 x 297 mm'."""
    w, h = w_pt * PT_TO_MM, h_pt * PT_TO_MM
    short, long_ = sorted((w, h))
    for name, (a, b) in _ISO.items():
        if abs(short - a) <= 6 and abs(long_ - b) <= 6:
            return f"{name} {'landscape' if w > h else 'portrait'}"
    return f"{w:.0f} x {h:.0f} mm"


_RATIO = r"(\d+(?:[.,]\d+)?)\s*[:/]\s*(\d+(?:[.,]\d+)?)"
# "Echelle : 1/100", "SCALE 1:50", "Ech. 2.5:1000"...
_SCALE_RE = re.compile(
    r"(?:[ée]chelle|scale|ech\.?|esc\.?|escala|ma[ßs]stab)\s*[:=]?\s*"
    + _RATIO, re.IGNORECASE)
# a text that is ONLY a ratio, e.g. "1:200" or "2.5:1000" under a scale bar
_RATIO_ALONE_RE = re.compile(r"^\s*" + _RATIO + r"\s*$", re.MULTILINE)


def _ratio(a: str, b: str) -> Optional[float]:
    try:
        x, y = float(a.replace(",", ".")), float(b.replace(",", "."))
    except ValueError:
        return None
    if x <= 0 or y < x:
        return None
    n = y / x
    return n if 1 <= n <= 10000 else None


def _round_scale(n: float) -> Optional[float]:
    """1:400 -> 400; 1:2.5 -> 2.5; odd results (3/4 inch) -> None."""
    if abs(n - round(n)) < 1e-6:
        return float(round(n))
    if abs(n * 2 - round(n * 2)) < 1e-6:
        return n
    return None


def detect_scale(text: str) -> Optional[float]:
    """Drawing scale written on the sheet. Returns N of 1:N (an int-valued
    float such as 400.0), or None when absent or ambiguous (several
    different scales on the sheet, e.g. details).

    Recognised: a scale keyword followed by a ratio ('Echelle : 1/100',
    'SCALE 1:50', 'Ech. 2.5:1000'), or a text made only of a ratio
    ('1:200', '2.5:1000' as printed above a scale bar)."""
    text = text or ""
    found = set()
    for m in _SCALE_RE.finditer(text):
        n = _ratio(m.group(1), m.group(2))
        n = _round_scale(n) if n else None
        if n:
            found.add(n)
    if not found:
        for m in _RATIO_ALONE_RE.finditer(text):
            a = m.group(1)
            n = _ratio(a, m.group(2))
            n = _round_scale(n) if n else None
            # alone, "1/2" or "3/4" may be fractions: ask for a real scale
            if n and n >= 5 and (float(a.replace(",", ".")) == 1
                                 or n == round(n)):
                found.add(n)
    if len(found) != 1:
        return None
    n = found.pop()
    return int(n) if n == int(n) else n


def inspect_page(page) -> PageInfo:
    """Classify one page quickly (no full extraction)."""
    rect = page.rect
    info = PageInfo(number=page.number + 1, width_pt=rect.width,
                    height_pt=rect.height, rotation=page.rotation % 360,
                    paper=paper_size_name(rect.width, rect.height))
    try:
        info.vector_count = sum(len(p.get("items", ()))
                                for p in page.get_cdrawings())
    except Exception:                                      # pragma: no cover
        info.vector_count = 0
    try:
        info.text_count = len(page.get_text("words"))
    except Exception:                                      # pragma: no cover
        info.text_count = 0
    try:
        area = max(rect.width * rect.height, 1e-9)
        cov = 0.0
        for im in page.get_image_info():
            bb = pymupdf.Rect(im["bbox"]) & rect
            if not bb.is_empty:
                cov += bb.width * bb.height
        info.image_coverage = min(cov / area, 1.0)
    except Exception:                                      # pragma: no cover
        info.image_coverage = 0.0
    info.kind = classify(info.vector_count, info.image_coverage,
                         info.text_count)
    return info


def inspect_document(path: str, with_pages: bool = True) -> DocumentInfo:
    """Metadata + per-page classification. Never raises (see .error)."""
    info = DocumentInfo(path=path)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        info.error = f"Cannot open PDF: {exc}"
        return info
    try:
        info.encrypted = bool(doc.needs_pass)
        info.page_count = doc.page_count
        if info.encrypted:
            info.error = "The PDF is password-protected."
            return info
        meta = doc.metadata or {}
        info.title = meta.get("title") or ""
        info.creator = meta.get("creator") or ""
        info.producer = meta.get("producer") or ""
        info.is_autocad = is_autocad_pdf(doc)
        try:
            ocgs = doc.get_ocgs() or {}
            info.ocg_layers = sorted({v.get("name", "") for v in ocgs.values()
                                      if v.get("name")})
        except Exception:                                  # pragma: no cover
            info.ocg_layers = []
        if with_pages:
            info.pages = [inspect_page(p) for p in doc]
    finally:
        doc.close()
    return info


def render_thumbnail(path_or_doc, page_index: int, max_px: int = 220,
                     doc=None) -> Optional[bytes]:
    """PNG bytes of a page thumbnail (longest side = max_px)."""
    own = doc is None and isinstance(path_or_doc, str)
    d = pymupdf.open(path_or_doc) if own else (doc or path_or_doc)
    try:
        page = d[page_index]
        z = max_px / max(page.rect.width, page.rect.height)
        return page.get_pixmap(matrix=pymupdf.Matrix(z, z),
                               alpha=False).tobytes("png")
    except Exception:
        return None
    finally:
        if own:
            d.close()
