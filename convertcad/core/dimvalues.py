"""
dimvalues.py — the VALUE of a dimension (used by annotations.py).

* Which texts can be a value: DIM_TEXT_RE (plain measurements) and
  DIM_VALUE_RE (also with a label, a count, brackets, a tolerance or a
  remark).
* The number a value gives (value_number), for the scale check.
* Values the PDF splits in several texts (combine_split_values): "3" and a
  small raised "50" (3⁵⁰, metres with the centimetres written small), a
  stacked fraction, a stacked tolerance, "25" followed by a small "±0.1".
* The scale check (ScaleVotes): a value should equal the measured length x
  the scale. The scale is voted by the clear dimensions of the sheet
  (several scales can live on one sheet: details), or is the one read on
  the sheet.

No Qt, no ezdxf: plain Python.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from .extractor import Point, RawText

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
# Text that *looks like* a measurement: "3500", "3 500", "3.50", "12,5",
# "R25", "Ø60", "45°", "1200 mm", "⌒785", "3⁵⁰" (metres with the
# centimetres written small), feet-inches "12'-6\"", "4'-3 1/2\"", "10'"...
DIAMETER_SIGNS = "Øø⌀∅Φφ"    # Ø ø ⌀ ∅ Φ φ
ARC_SIGN = "⌒"                                     # ⌒ (arc length)
SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_TO_SUPER = str.maketrans("0123456789", SUPERSCRIPTS)
_FROM_SUPER = str.maketrans(SUPERSCRIPTS, "0123456789")
_NUMBER = (r"(?:\d{1,3}(?:[   ]\d{3})+|\d{1,7})"
           r"(?:[.,]\d{1,3})?")
_METRIC = (_NUMBER + r"(?:[" + SUPERSCRIPTS + r"]{1,2})?\s*"
           r"(?:mm|cm|m|MM|CM|M|°)?")
_FRACTION = r"(?:\d{1,3}/\d{1,3}|[½¼¾⅛⅜⅝⅞])"
_INCHES = (r"(?:\d{1,3}(?:[.,]\d{1,4})?(?:[\s-]?" + _FRACTION + r")?|"
           + _FRACTION + r")\s?[\"″”]")
_FEET = r"\d{1,5}(?:[.,]\d{1,4})?\s?['′’]"
_IMPERIAL = r"(?:" + _FEET + r"(?:\s?-?\s?" + _INCHES + r")?|" + _INCHES + ")"
_MEASURE = (r"[~±≈R" + DIAMETER_SIGNS + ARC_SIGN + r"]?\s?(?:" + _IMPERIAL
            + "|" + _METRIC + ")")
DIM_TEXT_RE = re.compile("^" + _MEASURE + "$")

# The VALUE of a dimension may also carry a label or a count ("L=3500",
# "H = 2.50", "2x1500"), brackets ("(3500)"), a tolerance ("3500 ±5",
# "25 +0.1/-0.2"), an ISO fit after a diameter ("Ø20 H7"), a remark
# ("3500 (TYP.)", "3500*", "1500 c/c"), or be "EQ". Such a text is a
# DOUBTFUL value: accepted when terminators and line agree AND it agrees
# with the scale (or nothing tells the scale: then on the review layer);
# when nothing matches it stays an ordinary text (often a note).
# A rebar mark ("5 HA12", "4T16"), a grid mark ("20 A1") is never a value.
_LABEL = r"(?:[A-Za-z]{1,3}\.?\s?[=:]\s?|[1-9]\s?[xX×]\s?)"   # L= / 2x
_TOLERANCE = (r"(?:\s?(?:±|\+/-)\s?\d{1,4}(?:[.,]\d{1,3})?"
              r"|\s?[+-]\d{1,4}(?:[.,]\d{1,3})?\s?/\s?[+-]?\d{1,4}"
              r"(?:[.,]\d{1,3})?)")
_FIT = r"(?:\s?[A-Za-z]{1,2}\d{1,2}(?:/[a-z]{1,2}\d{1,2})?)"
_REMARK = (r"(?:\s?\*|\s*\(?\s*(?:TYP|Typ|typ|MAX|Max|max|MIN|Min|min|"
           r"ENV|Env|env|CA|ca|EQ|Eq|eq|c/c|C/C)\.?\s*\)?)")
DIM_VALUE_RE = re.compile(
    "^(?:" + _LABEL + r")?(?:\(\s?" + _MEASURE + r"\s?\)|" + _MEASURE
    + ")(?:" + _TOLERANCE + ")?(?:" + _REMARK + "){0,2}$"
    "|^(?:[1-9]\\s?[xX×]\\s?)?[" + DIAMETER_SIGNS + r"]\s?" + _NUMBER
    + _FIT + "(?:" + _REMARK + ")?$"
    r"|^(?:EQ|Eq|eq)\.?$")

# Radius "R25", "R 12.5"; diameter "Ø60", "2xØ12", "%%c60" (AutoCAD code)
RADIUS_RE = re.compile(r"^(?:\d{1,3}\s?[xX×]\s?)?R\s?\d")
DIAMETER_RE = re.compile(r"^(?:\d{1,3}\s?[xX×]\s?)?(?:[" + DIAMETER_SIGNS
                         + r"]|%%[cC])\s?\d")
# Angle "45°", "22.5°", "30°15'", "12°30'15\""
ANGLE_RE = re.compile(
    r"^(\d{1,3}(?:[.,]\d{1,4})?)\s*°"
    r"(?:\s*(\d{1,2}(?:[.,]\d+)?)\s*['′])?"
    r"(?:\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"″])?$")


def is_plain(text: str) -> bool:
    """A plain measurement (no label, remark...): a sure value."""
    return bool(DIM_TEXT_RE.match(text.strip()))


def is_value(text: str) -> bool:
    """Plain or doubtful dimension value."""
    return bool(DIM_VALUE_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# The number a value gives
# ---------------------------------------------------------------------------
_HEAD = re.compile(r"^(?:[A-Za-z]{1,3}\.?\s?[=:]\s?|[1-9]\s?[xX×]\s?)")
_TAIL_REMARK = re.compile(
    r"(?:\s?\*|\s*\(?\s*(?:TYP|Typ|typ|MAX|Max|max|MIN|Min|min|ENV|Env|env|"
    r"CA|ca|EQ|Eq|eq|c/c|C/C)\.?\s*\)?)$")
_TAIL_TOLERANCE = re.compile(_TOLERANCE + "$")
_TAIL_FIT = re.compile(_FIT + "$")
_VULGAR = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅛": 0.125, "⅜": 0.375,
           "⅝": 0.625, "⅞": 0.875}
_METRIC_RE = re.compile(
    r"(\d{1,3}(?:[   ]\d{3})+|\d{1,7})([.,]\d{1,3})?"
    r"([" + SUPERSCRIPTS + r"]{1,2})?\s*(mm|cm|m|MM|CM|M)?")
_FEET_RE = re.compile(r"(\d{1,5}(?:[.,]\d{1,4})?)\s?['′’](?:\s?-?\s?(.*))?")
_INCH_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{1,4})?)?\s?(?:[\s-]?(?:(\d{1,3})/(\d{1,3})|"
    r"([½¼¾⅛⅜⅝⅞])))?")


def value_number(text: str) -> Optional[Tuple[float, str]]:
    """(number, family) written in a dimension value, family "metric" (the
    number as written: mm, cm or m — the scale check works modulo powers of
    ten) or "imperial" (inches). None for "EQ", angles and non-values."""
    s = text.strip()
    if not s or s.upper().rstrip(".") == "EQ":
        return None
    s = _HEAD.sub("", s)
    for _ in range(2):
        s = _TAIL_REMARK.sub("", s).strip()
    s = _TAIL_TOLERANCE.sub("", s).strip()
    if s[:1] in DIAMETER_SIGNS:
        s = _TAIL_FIT.sub("", s).strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    s = s.lstrip("~±≈R" + DIAMETER_SIGNS + ARC_SIGN).strip()
    if not s or "°" in s:
        return None
    inches = _imperial_inches(s)
    if inches is not None:
        return inches, "imperial"
    m = _METRIC_RE.fullmatch(s)
    if not m:
        return None
    whole = re.sub(r"[   ]", "", m.group(1))
    if m.group(3):                         # 3⁵⁰ -> 3.50
        return float(whole + "." + m.group(3).translate(_FROM_SUPER)), \
            "metric"
    dec = (m.group(2) or "").replace(",", ".")
    return float(whole + dec), "metric"


def _imperial_inches(s: str) -> Optional[float]:
    """Feet-inches written in s, in inches ("12'-6\"" -> 150)."""
    feet, rest = 0.0, s
    m = _FEET_RE.fullmatch(s)
    if m:
        feet = float(m.group(1).replace(",", "."))
        rest = (m.group(2) or "").strip()
        if not rest:
            return feet * 12.0
    if not rest or rest[-1] not in "\"″”":
        return None
    rest = rest[:-1].strip()
    m2 = _INCH_RE.fullmatch(rest)
    if not rest or not m2 or not any(m2.groups()):
        return None
    inches = float(m2.group(1).replace(",", ".")) if m2.group(1) else 0.0
    if m2.group(2):
        inches += int(m2.group(2)) / max(int(m2.group(3)), 1)
    if m2.group(4):
        inches += _VULGAR[m2.group(4)]
    return feet * 12.0 + inches


# ---------------------------------------------------------------------------
# Values split in several texts
# ---------------------------------------------------------------------------
@dataclass
class CompositeText(RawText):
    """One value written as several PDF texts. `text` is the value as
    plain text ("3⁵⁰", "3 1/2", "25 +0.1/-0.2"); `mtext` the same with MTEXT
    stacking codes for the CAD dimension ("3\\S50^ ;", "3\\S1/2;",
    "25\\S+0.1^ -0.2;" — the space after ^ is part of the code); `parts`
    the PDF texts it is made of."""
    parts: List[RawText] = field(default_factory=list)
    mtext: str = ""


_MAIN_RE = re.compile(r"^(?:[" + DIAMETER_SIGNS + r"R]\s?)?\d[\d   ]*"
                      r"(?:[.,]\d*)?$|^\d{1,5}\s?['′’]\s?-?\s?\d{0,3}$")
_DIGITS_RE = re.compile(r"^\d{1,3}$")
_TOL_PART_RE = re.compile(r"^(?:[+-]\s?\d{1,4}(?:[.,]\d{1,3})?|0)$")


def _frame(main: RawText):
    """Reading direction and 'up' of a text, page coordinates (y down)."""
    a = math.radians(main.rotation)
    return (math.cos(a), -math.sin(a)), (-math.sin(a), -math.cos(a))


def _width(t: RawText) -> float:
    return t.width or 0.55 * t.height * len(t.text)


def combine_split_values(texts: Iterable[RawText]) -> List[CompositeText]:
    """Values the PDF wrote in several texts: a number followed by smaller
    texts, raised (superscript), stacked (fraction, tolerance) or "±...".
    The parts are left in `texts`; the caller uses the composites instead
    of them."""
    from .spatial import GridIndex
    pool = [t for t in texts if t.text.strip()]
    index: GridIndex[RawText] = GridIndex(24.0)
    for t in pool:
        index.insert(t, (t.origin[0], t.origin[1], t.origin[0], t.origin[1]))
    out: List[CompositeText] = []
    taken: set = set()
    for main in pool:
        s = main.text.strip()
        if id(main) in taken or not _MAIN_RE.match(s):
            continue
        h = max(main.height, 0.5)
        d, up = _frame(main)
        w = _width(main)
        end = (main.origin[0] + d[0] * w, main.origin[1] + d[1] * w)
        parts = []
        for t in index.near(end[0], end[1], 1.6 * h):
            if t is main or id(t) in taken:
                continue
            if not 0.3 * h <= t.height <= 0.82 * h:
                continue
            if abs((t.rotation - main.rotation + 180.0) % 360.0 - 180.0) > 3.0:
                continue
            vx, vy = t.origin[0] - end[0], t.origin[1] - end[1]
            dx = vx * d[0] + vy * d[1]               # after the main text
            dy = vx * up[0] + vy * up[1]             # above its baseline
            if -0.35 * h <= dx <= 0.6 * h and -0.6 * h <= dy <= 1.0 * h:
                parts.append((dx, dy, t))
        if not parts:
            continue
        comp = _composite(main, s, parts, d)
        if comp is not None:
            out.append(comp)
            taken.add(id(main))
            taken.update(id(p) for p in comp.parts[1:])
    return out


def _composite(main: RawText, s: str, parts, d) -> Optional[CompositeText]:
    h = max(main.height, 0.5)
    raised = [p for p in parts if p[1] >= 0.25 * h]
    lowered = [p for p in parts if p[1] < 0.1 * h]
    plain = mtext = None
    used: List[RawText] = []
    base = s.rstrip(".,").strip()
    # stacked: one part above, one below, one over the other
    for ux, _uy, up_t in raised:
        for lx, _ly, lo_t in lowered:
            if abs(ux - lx) > 0.5 * max(_width(up_t), _width(lo_t), 0.5):
                continue
            a, b = up_t.text.strip(), lo_t.text.strip()
            if _DIGITS_RE.match(a) and _DIGITS_RE.match(b) and int(b) > 0 \
                    and "'" not in s and int(a) < int(b):
                plain, mtext = f"{base} {a}/{b}", f"{base}\\S{a}/{b};"
            elif _TOL_PART_RE.match(a.replace(" ", "")) and \
                    _TOL_PART_RE.match(b.replace(" ", "")):
                a, b = a.replace(" ", ""), b.replace(" ", "")
                plain, mtext = f"{base} {a}/{b}", f"{base}\\S{a}^ {b};"
            if plain:
                used = [up_t, lo_t]
                break
        if plain:
            break
    if plain is None:
        pm = [p for p in parts if p[2].text.strip().startswith(("±", "+/-"))]
        if pm:
            tol = pm[0][2].text.strip()
            plain, mtext, used = f"{base} {tol}", f"{base}{tol}", [pm[0][2]]
    if plain is None and len(raised) == 1 and not lowered:
        part = raised[0][2].text.strip()
        if _DIGITS_RE.match(part) and len(part) <= 2 and "'" not in s:
            plain = base + part.translate(_TO_SUPER)
            mtext = f"{base}\\S{part}^ ;"
            used = [raised[0][2]]
    if plain is None:
        return None
    # a fraction written in inches: the inch mark may follow
    inch = [p for p in parts if p[2].text.strip() in ("\"", "″", "”")
            and p[2] not in used]
    if inch and "/" in plain:
        plain, mtext = plain + "\"", mtext + "\""
        used.append(inch[0][2])
    far = max(used, key=lambda t: (t.origin[0] - main.origin[0]) * d[0]
              + (t.origin[1] - main.origin[1]) * d[1])
    span = ((far.origin[0] - main.origin[0]) * d[0]
            + (far.origin[1] - main.origin[1]) * d[1]) + _width(far)
    return CompositeText(
        text=plain, origin=main.origin, height=main.height,
        rotation=main.rotation, color=main.color, font=main.font,
        pdf_layer=main.pdf_layer, source=main.source,
        width=max(span, _width(main)), cap_height=main.cap_height,
        flags=main.flags, parts=[main] + used, mtext=mtext)


def text_ids(t: RawText) -> set:
    """ids of the PDF texts a value is made of (itself, or its parts)."""
    if isinstance(t, CompositeText):
        return {id(t)} | {id(p) for p in t.parts}
    return {id(t)}


# ---------------------------------------------------------------------------
# Scale check
# ---------------------------------------------------------------------------
_UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def _frac(x: float) -> float:
    return x - math.floor(x)


def _circ(a: float, b: float) -> float:
    """Distance between two decimal-log fractions (modulo 1)."""
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


class ScaleVotes:
    """The scale(s) of a sheet: value / measured length (page points).

    Metric values are compared modulo powers of ten (a sheet mixing mm and
    m, or "1,250" read as 1.25 or 1250, gives one scale); feet-inches give
    their own scale. A scale needs two clear dimensions agreeing, or the
    scale read on the sheet (or calibrated) — the default scale of the
    converter is not trusted."""

    TOL = 0.025                  # relative, + the drawing precision

    def __init__(self, units_per_pt: Optional[float] = None,
                 units: str = "mm", known: bool = False):
        self._metric: List[float] = []
        self._imperial: List[float] = []
        self.refs_metric: List[float] = []
        self.refs_imperial: List[float] = []
        self.declared_metric: Optional[float] = None
        self.declared_imperial: Optional[float] = None
        if known and units_per_pt and units_per_pt > 0:
            self.declared_metric = _frac(math.log10(units_per_pt))
            mm = units_per_pt * _UNIT_MM.get(units, 1.0)
            self.declared_imperial = math.log10(mm / 25.4)

    @staticmethod
    def _tol(span_pt: float) -> float:
        rel = max(ScaleVotes.TOL, 1.5 / max(span_pt, 1e-6))
        return math.log10(1.0 + min(rel, 0.5))

    def add(self, number: float, family: str, span_pt: float) -> None:
        if number <= 0 or span_pt <= 0:
            return
        r = math.log10(number / span_pt)
        (self._metric if family == "metric" else self._imperial).append(r)

    def finish(self) -> None:
        tol = math.log10(1.0 + 0.03)
        self.refs_metric = _clusters([_frac(r) for r in self._metric], tol,
                                     circular=True)
        self.refs_imperial = _clusters(self._imperial, tol, circular=False)

    @property
    def known(self) -> bool:
        return bool(self.refs_metric or self.refs_imperial
                    or self.declared_metric is not None)

    def check(self, number: Optional[float], family: str,
              span_pt: float) -> Optional[bool]:
        """True: agrees with a scale of the sheet; False: a scale is known
        and none agrees; None: nothing to compare with."""
        if number is None or number <= 0 or span_pt <= 0:
            return None
        r = math.log10(number / span_pt)
        tol = self._tol(span_pt)
        if family == "metric":
            refs = list(self.refs_metric)
            if self.declared_metric is not None:
                refs.append(self.declared_metric)
            if not refs:
                return None
            return any(_circ(_frac(r), x) <= tol for x in refs)
        refs = list(self.refs_imperial)
        if self.declared_imperial is not None:
            refs.append(self.declared_imperial)
        if not refs:
            return None
        return any(abs(r - x) <= tol for x in refs)


def _clusters(values: List[float], tol: float, circular: bool) -> List[float]:
    """Centres of the groups of >= 2 values lying within tol of each
    other."""
    if len(values) < 2:
        return []
    vals = sorted(values)
    groups: List[List[float]] = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    if circular and len(groups) > 1 and \
            (vals[0] + 1.0) - groups[-1][-1] <= tol:   # wraps around 0/1
        groups[0] = [x - 1.0 for x in groups[-1]] + groups[0]
        groups.pop()
    out = []
    for g in groups:
        if len(g) >= 2:
            c = sum(g) / len(g)
            out.append(_frac(c) if circular else c)
    return out


def center_of(t: RawText) -> Point:
    return t.center()
