"""
text_export.py — every text of a converted drawing in a list, with its
sheet and its position: a .csv file (spreadsheets, programs, search
indexes) and a .txt file (to read, or to feed a search engine).

The texts are read back from the finished DXF document, so the list holds
exactly what the drawing shows: texts and paragraphs, dimension values,
leader notes, recovered SHX texts, OCR texts of scanned sheets, values left
on layer DIM_RAW and texts inside blocks. Layer edits made before saving
(renamed or removed layers) are already applied.

Each text has two positions:
- x, y: its insertion point in the drawing (drawing units), to find it in
  the CAD program;
- sheet_x_mm, sheet_y_mm: the same point on the paper sheet, in mm from the
  sheet's top-left corner, to find it on the PDF.
"""

import bisect
import csv
import math
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .. import APP_NAME, APP_VERSION
from .constants import (LAYER_DIM_RAW, LAYER_LEADER, LAYER_SHX_TEXT,
                        LAYER_TRACE_TEXT)

PT_MM = 25.4 / 72                     # one PDF point in millimetres
FORMATS = ("csv", "txt", "both")      # Options.export_texts ("" = off)
CSV_COLUMNS = ("pdf", "drawing", "page", "kind", "layer", "text", "x", "y",
               "rotation", "height", "sheet_x_mm", "sheet_y_mm")


@dataclass
class TextRow:
    pdf: str              # source PDF file name
    drawing: str          # DXF / DWG file name holding the text
    page: int             # PDF page (sheet) number
    kind: str             # text | paragraph | dimension | leader | value |
                          # shx | ocr | block
    layer: str
    text: str             # plain text; lines of a paragraph separated by \n
    x: float              # insertion point in the drawing (drawing units)
    y: float
    rotation: Optional[float]  # degrees, counter-clockwise (None: unknown)
    height: float         # text height in drawing units (0 = unknown)
    sheet_x_mm: float     # the same point on the sheet, from its top-left
    sheet_y_mm: float     # corner


def list_title(pdf: str) -> str:
    """First line of the .txt list."""
    return f"{APP_NAME} {APP_VERSION} - texts of {pdf}"


def list_paths(base: str, fmt: str) -> List[str]:
    """Files written for `fmt` next to `base` (a path without extension):
    <base>_texts.csv and/or <base>_texts.txt."""
    exts = {"csv": [".csv"], "txt": [".txt"], "both": [".csv", ".txt"]}
    return [f"{base}_texts{ext}" for ext in exts.get(fmt, [])]


# ---------------------------------------------------------------------------
# Reading the texts of a DXF document
# ---------------------------------------------------------------------------
class _Sheets:
    """Which sheet a drawing point belongs to, and where it sits on it.

    `pages` are the report placements of ONE drawing file: {"page",
    "x_offset", "scale", "width_pt", "height_pt"}. Sheets lie side by side
    from left to right; a point belongs to the sheet whose strip holds it
    (the strips meet half way across the gap between two sheets)."""

    def __init__(self, pages: Sequence[dict]):
        self.pages = sorted(pages, key=lambda p: p.get("x_offset", 0.0))
        self.bounds = []
        for a, b in zip(self.pages, self.pages[1:]):
            right = a["x_offset"] + a["width_pt"] * a["scale"]
            self.bounds.append((right + b["x_offset"]) / 2)

    def locate(self, x: float, y: float) -> Tuple[int, float, float]:
        """(page number, sheet x mm, sheet y mm) of a drawing point."""
        if not self.pages:
            return 0, 0.0, 0.0
        p = self.pages[bisect.bisect_right(self.bounds, x)]
        s = p["scale"] or 1.0
        sx = (x - p["x_offset"]) / s * PT_MM
        sy = (p["height_pt"] - y / s) * PT_MM
        return int(p["page"]), sx, sy


_SUPER = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_STACK = re.compile(r"\\S([^;^/#]*)([\^/#])\s?([^;]*);")


def _unstack(m: "re.Match") -> str:
    """MTEXT stacking (\\S...;) as plain text: 3\\S50^ ; -> 3⁵⁰,
    25\\S+0.1^ -0.2; -> 25 +0.1/-0.2, 3\\S1/2; -> 3 1/2."""
    a, sep, b = m.group(1).strip(), m.group(2), m.group(3).strip()
    if sep == "^" and not b:                         # raised (superscript)
        return a.translate(_SUPER) if a.isdigit() else a
    return f" {a}/{b}"


def plain_mtext(content: str) -> str:
    """Readable text of an MTEXT content string (codes removed)."""
    from ezdxf.tools.text import plain_mtext as _plain
    return _plain(_STACK.sub(_unstack, content)).strip()


def _kind(layer: str, default: str) -> str:
    return {LAYER_LEADER: "leader", LAYER_DIM_RAW: "value",
            LAYER_SHX_TEXT: "shx", LAYER_TRACE_TEXT: "ocr"}.get(layer,
                                                               default)


def _angle(vec) -> float:
    return math.degrees(math.atan2(vec[1], vec[0])) % 360.0


def _text_items(e, kind_default: Optional[str] = None):
    """(kind, layer, text, x, y, rotation, height) of one entity; several
    for a block reference holding texts. Entities without text: none."""
    t = e.dxftype()
    layer = e.dxf.get("layer", "0")
    if t == "TEXT":
        align, p1, p2 = e.get_placement()
        p = p2 if p2 is not None and align.name != "LEFT" else p1
        yield (kind_default or _kind(layer, "text"), layer,
               e.plain_text().strip(), p[0], p[1],
               e.dxf.get("rotation", 0.0), e.dxf.get("height", 0.0))
    elif t == "MTEXT":
        p = e.dxf.insert
        yield (kind_default or _kind(layer, "paragraph"), layer,
               plain_mtext(e.text), p[0], p[1], e.get_rotation(),
               e.dxf.get("char_height", 0.0))
    elif t == "DIMENSION":
        text = e.dxf.get("text", "")
        if text in ("", "<>"):                          # measured value
            try:
                text = f"{e.get_measurement():.6g}"
            except Exception:                           # pragma: no cover
                text = ""
        p = (e.dxf.text_midpoint if e.dxf.hasattr("text_midpoint")
             else e.dxf.defpoint)
        try:
            height = e.override().get("dimtxt") or 0.0
        except Exception:                               # pragma: no cover
            height = 0.0
        yield ("dimension", layer, plain_mtext(text), p[0], p[1],
               e.dxf.get("text_rotation", None), height)
    elif t == "MULTILEADER":
        mt = getattr(e.context, "mtext", None)
        if mt is not None and mt.default_content:
            p = mt.insert
            yield ("leader", layer, plain_mtext(mt.default_content), p[0],
                   p[1], _angle(mt.text_direction),
                   getattr(e.context, "char_height", 0.0))


class _Blocks:
    """Block definitions holding texts (looked at once per block name)."""

    def __init__(self, doc):
        self.doc = doc
        self.known: Dict[str, bool] = {}

    def has_text(self, name: str, depth: int = 0) -> bool:
        if name not in self.known:
            self.known[name] = False                    # no endless loop
            block = self.doc.blocks.get(name)
            found = False
            for b in block or []:
                bt = b.dxftype()
                if bt in ("TEXT", "MTEXT") or (
                        bt == "INSERT" and depth < 8
                        and self.has_text(b.dxf.name, depth + 1)):
                    found = True
                    break
            self.known[name] = found
        return self.known[name]


def _items(e, blocks: _Blocks, depth: int = 0):
    if e.dxftype() == "INSERT":
        for att in e.attribs:                            # attribute values
            p = att.dxf.insert
            yield ("block", att.dxf.get("layer", "0"),
                   att.plain_text().strip(), p[0], p[1],
                   att.dxf.get("rotation", 0.0), att.dxf.get("height", 0.0))
        if depth < 8 and blocks.has_text(e.dxf.name):
            for v in e.virtual_entities():
                if v.dxftype() == "INSERT":
                    yield from _items(v, blocks, depth + 1)
                else:
                    yield from _text_items(v, "block")
        return
    yield from _text_items(e)


def texts_of(doc, pages: Sequence[dict], drawing: str,
             pdf: str) -> List[TextRow]:
    """Every text of the model space of a DXF document, in drawing order.

    `pages`: the report placements of this drawing file (one per sheet it
    holds); `drawing` and `pdf`: the file names written in the list."""
    sheets = _Sheets(pages)
    blocks = _Blocks(doc)
    rows: List[TextRow] = []
    for e in doc.modelspace():
        for kind, layer, text, x, y, rot, h in _items(e, blocks):
            if not text:
                continue
            page, sx, sy = sheets.locate(x, y)
            rows.append(TextRow(pdf=pdf, drawing=drawing, page=page,
                                kind=kind, layer=layer, text=text,
                                x=float(x), y=float(y),
                                rotation=(None if rot is None
                                          else float(rot) % 360.0),
                                height=float(h or 0.0),
                                sheet_x_mm=sx, sheet_y_mm=sy))
    return rows


# ---------------------------------------------------------------------------
# Writing the lists
# ---------------------------------------------------------------------------
def reading_order(rows: Iterable[TextRow]) -> List[TextRow]:
    """Sheet by sheet, top to bottom, then left to right (texts less than
    half a text height apart vertically are on the same line)."""
    out: List[TextRow] = []
    by_page: Dict[int, List[TextRow]] = {}
    for r in rows:
        by_page.setdefault(r.page, []).append(r)
    for page in sorted(by_page):
        items = sorted(by_page[page], key=lambda r: (r.sheet_y_mm,
                                                     r.sheet_x_mm))
        line: List[TextRow] = []
        top = 0.0
        for r in items:
            if line and r.sheet_y_mm - top > 1.5:
                out += sorted(line, key=lambda q: q.sheet_x_mm)
                line = []
            if not line:
                top = r.sheet_y_mm
            line.append(r)
        out += sorted(line, key=lambda q: q.sheet_x_mm)
    return out


def _num(v: float, decimals: int = 3) -> str:
    """1234.5 -> '1234.5', 100.0 -> '100' (no needless zeros)."""
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def write_csv(rows: Sequence[TextRow], path: str) -> None:
    """Comma-separated, UTF-8 with a BOM (Excel then reads the accents).
    A paragraph keeps its line breaks inside its quoted cell."""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for r in rows:
            w.writerow([r.pdf, r.drawing, r.page, r.kind, r.layer, r.text,
                        _num(r.x), _num(r.y),
                        "" if r.rotation is None else _num(r.rotation, 2),
                        _num(r.height), _num(r.sheet_x_mm, 1),
                        _num(r.sheet_y_mm, 1)])


def write_txt(rows: Sequence[TextRow], path: str, title: str,
              units: str) -> None:
    """One text per line, sheet by sheet: text  [x, y | sheet position |
    kind, layer]. The lines of a paragraph are joined with " // "."""
    drawings = list(dict.fromkeys(r.drawing for r in rows))
    out = [title,
           f"Drawing: {', '.join(drawings) or '-'} (units: {units}). "
           f"{len(rows)} text(s), in reading order.",
           "Each line: text  [x, y in the drawing | x, y on the sheet in mm "
           "from its top-left corner | kind, layer]", ""]
    page = None
    for r in rows:
        if r.page != page:
            page = r.page
            if out[-1]:
                out.append("")
            out.append(f"== Sheet {page} ==")
        text = " // ".join(s.strip() for s in r.text.splitlines()
                           if s.strip())
        out.append(f"{text}  [{_num(r.x, 2)}, {_num(r.y, 2)} | "
                   f"{_num(r.sheet_x_mm, 1)}, {_num(r.sheet_y_mm, 1)} mm | "
                   f"{r.kind}, {r.layer}]")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def write_lists(rows: Sequence[TextRow], base: str, fmt: str, pdf: str,
                units: str) -> List[str]:
    """Write <base>_texts.csv / .txt for `fmt` (csv | txt | both); `pdf`
    is the source PDF file name. Returns the paths written. Raises OSError
    when a file cannot be written."""
    title = list_title(pdf)
    ordered = reading_order(rows)
    written = []
    for path in list_paths(base, fmt):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if path.endswith(".csv"):
            write_csv(ordered, path)
        else:
            write_txt(ordered, path, title, units)
        written.append(path)
    return written
