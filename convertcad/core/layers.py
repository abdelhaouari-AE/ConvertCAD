"""
layers.py — STEP 3: assign every entity to an intelligent DXF layer.

Priority order (mirrors the best commercial converters):
  1. Native PDF layer (OCG) name, sanitized         -> kept as-is
  2. Entity role (text / hatch / image / dim ...)   -> dedicated role layers
  3. Style fingerprint, according to the naming mode:
       "style"  : colour + lineweight + linetype -> GEO_BLACK_050_CENTER
       "color"  : colour only                     -> GEO_BLACK
       "single" : everything on one layer         -> GEOMETRY

Rules are pure functions: easy to unit-test and to extend.
"""

import colorsys
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterable, Tuple

from .constants import (LAYER_DEFAULT, LAYER_HATCH, LAYER_IMAGE,
                        LAYER_SHX_STROKES, LAYER_SINGLE, LAYER_TEXT)

if TYPE_CHECKING:                       # typing only: keeps this module light
    from .extractor import Style        # (extractor imports PyMuPDF)

_LT_SUFFIX = {"CONTINUOUS": "", "DASHED": "_DASH", "DASHDOT": "_DASHDOT",
              "CENTER": "_CENTER", "PHANTOM": "_PHANTOM", "HIDDEN": "_HIDDEN",
              "DOT": "_DOT", "DIVIDE": "_DIVIDE"}


def sanitize(name: str) -> str:
    """Make a string safe as a DXF layer name (AutoCAD forbids <>/\\":;?*|=`)."""
    clean = re.sub(r'[<>/\\":;?*|=`,\x00-\x1f]', "_", name).strip()
    return clean[:120] or LAYER_DEFAULT


# hue upper limit (degrees) -> colour word, for readable layer names
_HUE_NAMES = ((15, "RED"), (40, "ORANGE"), (70, "YELLOW"), (160, "GREEN"),
              (195, "CYAN"), (255, "BLUE"), (330, "MAGENTA"), (360, "RED"))


def color_name(rgb: Tuple[int, int, int]) -> str:
    """Readable colour name for layer names: BLACK, GRAY, LTGRAY, RED,
    ORANGE, YELLOW, GREEN, CYAN, BLUE, MAGENTA (+ LT/DK prefixes).
    Similar tints share a name (and therefore a layer); the exact colour is
    still kept on each entity when it differs from its layer colour."""
    r, g, b = (c / 255.0 for c in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.16:
        return "BLACK"
    if s < 0.15:                                     # neutral greys
        if v > 0.92:
            return "WHITE"
        return "LTGRAY" if v > 0.70 else "GRAY" if v > 0.40 else "DKGRAY"
    deg = h * 360.0
    name = next((n for limit, n in _HUE_NAMES if deg < limit), "RED")
    if v < 0.55:
        return "DK" + name
    if s < 0.45 and v > 0.80:
        return "LT" + name
    return name


def layer_for_style(style: "Style", use_pdf_layers: bool = True,
                    mode: str = "style") -> str:
    """Geometry layer name for a stroke style."""
    if style.pdf_layer == LAYER_SHX_STROKES:        # role layer, always
        return LAYER_SHX_STROKES
    if use_pdf_layers and style.pdf_layer:
        return sanitize(style.pdf_layer)
    if mode == "single":
        return LAYER_SINGLE
    cname = color_name(style.color)
    if mode == "color":
        return f"GEO_{cname}"
    width = f"{style.width:.2f}".replace(".", "")      # 0.50 -> 050
    return f"GEO_{cname}_{width}" + _LT_SUFFIX.get(style.linetype, "_DASH")


@dataclass
class LayerInfo:
    name: str
    rgb: Tuple[int, int, int]
    linetype: str = "CONTINUOUS"
    lineweight: int = -1             # DXF lineweight enum (25 = 0.25 mm)
    locked: bool = False
    description: str = ""
    off: bool = False                # created switched off (hidden)


_LW_ENUMS = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80,
             90, 100, 106, 120, 140, 158, 200, 211]


def lineweight_enum(width_pt: float) -> int:
    """Map a PDF stroke width (points -> mm on paper) to the closest enum."""
    mm = width_pt * 25.4 / 72.0
    return min(_LW_ENUMS, key=lambda c: abs(c / 100.0 - mm))


def build_layer_table(styles: Iterable["Style"], use_pdf_layers: bool = True,
                      mode: str = "style", has_text: bool = False,
                      has_hatch: bool = False, has_image: bool = False
                      ) -> Dict[str, LayerInfo]:
    """Collect the set of layers the DXF needs for these styles."""
    table: Dict[str, LayerInfo] = {}
    for st in styles:
        name = layer_for_style(st, use_pdf_layers, mode)
        if name in table:
            continue
        if name == LAYER_SHX_STROKES:
            table[name] = LayerInfo(name, st.color, off=True,
                                    description="AutoCAD SHX letter strokes "
                                                "(replaced by layer TEXT_SHX)")
            continue
        if mode == "single" and not (use_pdf_layers and st.pdf_layer):
            table[name] = LayerInfo(name, (0, 0, 0),
                                    description="All geometry")
            continue
        table[name] = LayerInfo(
            name=name, rgb=st.color,
            linetype=st.linetype if mode == "style" or st.pdf_layer
            else "CONTINUOUS",
            lineweight=lineweight_enum(st.width) if mode == "style" else -1,
            description="From PDF layer" if st.pdf_layer
            else "Grouped by style")
    if has_text:
        table[LAYER_TEXT] = LayerInfo(LAYER_TEXT, (0, 0, 0),
                                      description="Native PDF text")
    if has_hatch:
        table[LAYER_HATCH] = LayerInfo(LAYER_HATCH, (128, 128, 128),
                                       description="Solid fills")
    if has_image:
        table[LAYER_IMAGE] = LayerInfo(LAYER_IMAGE, (128, 128, 128),
                                       locked=True,
                                       description="Raster images (locked)")
    return table
