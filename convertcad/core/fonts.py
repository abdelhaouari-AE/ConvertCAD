"""
fonts.py — which CAD text style shows a PDF text like the original.

A PDF names the font of each text ("ABCDEF+Arial-BoldMT", "Times-Roman",
"CourierNewPSMT"...). ConvertCAD writes the text with a DXF text style that
uses the same Windows TrueType font, so the text keeps its look in AutoCAD:

  * size  — the DXF text height is the CAPITAL height. Each font has its own
            ratio (Arial 0.716 of the font size, Courier New only 0.571):
            using one ratio for all fonts made some texts too big;
  * width — when the text in the PDF is narrower or wider than the font
            draws it (condensed text, a font replaced by Arial), a width
            factor keeps its original length, so it ends where it ended
            in the PDF and stays aligned with the drawing;
  * bold and italic keep their own font file (arialbd.ttf, ariali.ttf...).

Fonts that are not recognised are shown with Arial, at the user's "text
height ratio" and with a width factor matching the PDF length.

Widths are measured with the PDF base fonts built into PyMuPDF, which have
the same widths as Arial (Helvetica), Times New Roman (Times) and Courier
New (Courier). Pure Python apart from that; no font file is read.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple


@dataclass(frozen=True)
class CadFont:
    family: str                  # "Arial", "Times New Roman"...
    bold: bool
    italic: bool
    file: str                    # TrueType file of the DXF text style
    cap: Optional[float]         # capital height / font size (None: unknown)
    measure: str                 # PyMuPDF base font for widths ("" = none)
    scale: float = 1.0           # this font's width / the measure font's width
    known: bool = True           # False: the PDF font was not recognised

    @property
    def style(self) -> str:
        """DXF text style name: 'Arial', 'Arial Bold', 'Arial Bold Italic'."""
        extra = " ".join(w for w, on in (("Bold", self.bold),
                                          ("Italic", self.italic)) if on)
        return f"{self.family} {extra}".strip()


# (name pattern, family, files (regular, bold, italic, bold italic),
#  capital height ratio, measure fonts (regular, bold, italic, bold italic),
#  width relative to the measure font). Ratios: OS/2 capital height of the
#  Windows fonts. Order matters: "arial narrow" before "arial".
_HELV = ("helv", "hebo", "heit", "hebi")
_TIMES = ("tiro", "tibo", "tiit", "tibi")
_COUR = ("cour", "cobo", "coit", "cobi")
_NONE = ("", "", "", "")
FAMILIES = [
    (r"arialnarrow|helvetica(narrow|condensed)|sansnarrow|liberationsansnarrow",
     "Arial Narrow", ("arialn.ttf", "arialnb.ttf", "arialni.ttf", "arialnbi.ttf"),
     0.716, _HELV, 0.82),
    (r"arial|helvetica|nimbussans|liberationsans|arimo|swiss721|freesans",
     "Arial", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
     0.716, _HELV, 1.0),
    (r"timesnewroman|times|nimbusroman|liberationserif|tinos|freeserif",
     "Times New Roman", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
     0.662, _TIMES, 1.0),
    (r"courier|nimbusmono|liberationmono|cousine|freemono",
     "Courier New", ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
     0.571, _COUR, 1.0),
    (r"calibri", "Calibri",
     ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
     0.632, _NONE, 1.0),
    (r"verdana", "Verdana",
     ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
     0.727, _NONE, 1.0),
    (r"tahoma", "Tahoma",
     ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
     0.727, _NONE, 1.0),
    (r"segoeui", "Segoe UI",
     ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
     0.700, _NONE, 1.0),
    (r"georgia", "Georgia",
     ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
     0.693, _NONE, 1.0),
    (r"trebuchet", "Trebuchet MS",
     ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
     0.715, _NONE, 1.0),
    # AutoCAD's own TrueType fonts (ISO 3098 lettering)
    (r"isocpeur|isocp", "ISOCPEUR",
     ("isocpeur.ttf", "isocpeur.ttf", "isocpeui.ttf", "isocpeui.ttf"),
     None, _NONE, 1.0),
    (r"isocteur|isoct", "ISOCTEUR",
     ("isocteur.ttf", "isocteur.ttf", "isocteui.ttf", "isocteui.ttf"),
     None, _NONE, 1.0),
]
_COMPILED = [(re.compile(p), *rest) for p, *rest in FAMILIES]

_BOLD_RE = re.compile(r"bold|black|heavy|semibold|demibold|demi|(?<=[a-z])bd$")
_ITALIC_RE = re.compile(r"italic|oblique|(?<=[a-z])it$|(?<=[-,])i$")

# PyMuPDF span flags
FLAG_ITALIC = 2
FLAG_BOLD = 16


def _clean(name: str) -> str:
    """'ABCDEF+Arial-BoldMT' -> 'arialboldmt' (subset prefix and separators
    removed, lower case)."""
    name = (name or "").split("+", 1)[-1]
    return re.sub(r"[\s\-_,.]", "", name).lower()


@lru_cache(maxsize=512)
def resolve(pdf_font: str, flags: int = 0) -> CadFont:
    """The CAD font that shows a text of this PDF font like the original."""
    raw = (pdf_font or "").split("+", 1)[-1].lower()
    clean = _clean(pdf_font)
    bold = bool(flags & FLAG_BOLD) or bool(_BOLD_RE.search(raw.replace(" ", "")))
    italic = bool(flags & FLAG_ITALIC) or bool(_ITALIC_RE.search(raw))
    k = (1 if bold else 0) + (2 if italic else 0)
    for pattern, family, files, cap, measure, scale in _COMPILED:
        if pattern.search(clean):
            return CadFont(family, bold, italic, files[k], cap, measure[k], scale)
    # not recognised: Arial, keeping the length of the PDF text
    return CadFont("Arial", bold, italic,
                   ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")[k],
                   None, _HELV[k], 1.0, known=False)


@lru_cache(maxsize=16)
def _base_font(code: str):
    import pymupdf
    return pymupdf.Font(code)


def natural_width(font: CadFont, text: str, cap_height: float
                  ) -> Optional[float]:
    """Length of `text` drawn with `font` at this capital height (same unit
    as cap_height), or None when it cannot be measured (font without known
    widths, or letters the base fonts do not have, e.g. Arabic)."""
    if not font.measure or not text or cap_height <= 0:
        return None
    try:
        base = _base_font(font.measure)
        if any(not base.has_glyph(ord(c)) for c in text if not c.isspace()):
            return None
        cap = font.cap or 0.716
        em = cap_height / cap                     # font size giving that cap
        return base.text_length(text, fontsize=em) * font.scale
    except Exception:                             # pragma: no cover
        return None


def width_factor(font: CadFont, text: str, cap_height: float,
                 pdf_length: float) -> float:
    """DXF width factor that gives the text its PDF length (1.0 when the
    font already matches within 4 %, or when it cannot be measured)."""
    if pdf_length <= 0:
        return 1.0
    nat = natural_width(font, text, cap_height)
    if not nat:
        return 1.0
    f = pdf_length / nat
    if abs(f - 1.0) <= 0.04:
        return 1.0
    return round(min(max(f, 0.3), 3.0), 3)


def style_files(font: CadFont) -> Tuple[str, str]:
    """(style name, font file) for the DXF STYLE table."""
    return font.style, font.file
