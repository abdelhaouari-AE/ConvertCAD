"""
options.py — every conversion option, with its default value.

The interface, the command-line tool, the batch mode, the presets and the
tests all fill ONE `Options` object; the engine reads it. Standard library
only, so the interface can build its settings panel at start-up without
loading the conversion libraries.
"""

from dataclasses import asdict, dataclass, fields
from typing import List, Optional

from .. import APP_VERSION
from .constants import (CURVE_PRECISION, DEFAULT_DXF_VERSION,
                        DEFAULT_LAYER_MODE, DEFAULT_PAGE_MODE, DEFAULT_UNITS,
                        DWG_DXF_VERSION, OCR_ENGINES, OUTPUT_FORMATS)
from .units import effective_denominator


@dataclass
class Options:
    """Every conversion option, with its default value."""
    # ---- pages & area ----
    pages: Optional[List[int]] = None      # 1-based page numbers; None = all
    clip_rect: Optional[List[float]] = None  # [x0, y0, x1, y1] page points
                                           # (displayed sheet); None = whole
                                           # sheet. Applies to every sheet.
    # ---- geometry ----
    fit_arcs: bool = True                  # Bezier -> ARC / CIRCLE
    join_polylines: bool = True            # touching segments -> LWPOLYLINE
    join_splines: bool = True              # Bezier chains -> one SPLINE
    curve_precision: str = "normal"        # fine | normal | loose
    hatches: bool = True                   # solid fills -> HATCH
    hatch_patterns: bool = True            # parallel-line hatching -> HATCH
    merge_dashes: bool = True              # dashes drawn as separate pieces
                                           # -> one line with a linetype
    ignore_white_fills: bool = True        # skip white masks / backgrounds
    ignore_background_fills: bool = True   # skip page-sized fills
    # ---- text ----
    text_entities: bool = True             # PDF text -> TEXT
    group_mtext: bool = True               # stacked lines -> MTEXT
    text_height_factor: float = 0.7        # cap height / font size
    shx_comments: bool = True              # AutoCAD SHX comments -> TEXT_SHX
    # ---- annotations ----
    dimensions: bool = True                # arrow dimensions -> DIMENSION
    tick_dimensions: bool = True           # oblique-tick dimensions
    leaders: bool = True                   # arrow + polyline + note -> leader
    # ---- layers & blocks ----
    use_pdf_layers: bool = True            # keep native PDF (OCG) layers
    layer_mode: str = DEFAULT_LAYER_MODE   # style | color | single
    recognize_linetypes: bool = True       # CENTER / DASHDOT / PHANTOM ...
    color_mode: str = "aci"                # aci (plot-style friendly) | true
    block_detection: bool = True           # repeated symbols -> BLOCK/INSERT
    block_min_repeats: int = 3
    block_rotations: bool = True           # rotated / mirrored copies too
    # ---- scanned pages ----
    raster_mode: bool = True               # trace scanned pages
    ocr: bool = True                       # OCR scanned text
    ocr_engine: str = "auto"               # auto | tesseract | rapidocr |
                                           # paddleocr (see core/ocr.py)
    ocr_lang: str = "eng+fra"
    ocr_vertical: bool = False             # second OCR pass for vertical text
    raster_dpi: int = 300
    use_pdf_text_layer: bool = True        # scanned PDF already searchable
    include_images: bool = True            # keep raster images (locked layer)
    # ---- scale & units ----
    units: str = DEFAULT_UNITS             # mm | cm | m
    scale_denominator: float = 50.0        # 1:N paper scale
    calibrated_units_per_pt: float = 0.0   # >0 overrides the paper scale
    auto_scale: bool = False               # read 1:N on each sheet (title
                                           # block); scale_denominator is the
                                           # fallback when none is found
    # ---- output ----
    output_format: str = "dxf"             # dxf | dwg
    dxf_version: str = DEFAULT_DXF_VERSION
    page_mode: str = DEFAULT_PAGE_MODE     # single | split
    page_gap_factor: float = 1.10          # spacing between pages (single)
    write_log: bool = True                 # <name>_log.txt next to the DXF

    # -------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Options":
        """Build from a (possibly older or partial) dict; unknown keys are
        ignored and missing keys keep their defaults — presets never break."""
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        opt = cls(**clean)
        if opt.curve_precision not in CURVE_PRECISION:
            opt.curve_precision = "normal"
        if opt.ocr_engine not in OCR_ENGINES:
            opt.ocr_engine = "auto"
        if opt.output_format not in OUTPUT_FORMATS:
            opt.output_format = "dxf"
        opt.clip_rect = normalize_rect(opt.clip_rect)
        return opt

    # ---- derived values ------------------------------------------------------
    def writer_dxf_version(self) -> str:
        """DXF version actually written. DWG files are produced from an
        AutoCAD 2000 DXF (the DWG version the bundled LibreDWG writes), so
        every entity is one that DWG 2000 can hold."""
        return DWG_DXF_VERSION if self.output_format == "dwg" \
            else self.dxf_version

    def scale_text(self) -> str:
        if self.calibrated_units_per_pt > 0:
            den = effective_denominator(self.calibrated_units_per_pt,
                                        self.units)
            return (f"calibrated ({self.calibrated_units_per_pt:.6g} "
                    f"{self.units}/pt, about 1:{den:.4g})")
        if self.auto_scale:
            return (f"read on each sheet (1:{self.scale_denominator:g} when "
                    f"none is written)")
        return f"1:{self.scale_denominator:g}"

    def describe(self) -> dict:
        """Options as written in the conversion log (English, stable keys)."""
        on = lambda b: "on" if b else "off"                      # noqa: E731
        area = "whole sheet"
        if self.clip_rect:
            x0, y0, x1, y1 = self.clip_rect
            area = (f"selected area {x1 - x0:.0f} x {y1 - y0:.0f} pt at "
                    f"({x0:.0f}, {y0:.0f})")
        fmt = ("DWG (AutoCAD 2000 format)" if self.output_format == "dwg"
               else f"DXF {self.dxf_version}")
        return {
            "Scale": self.scale_text(),
            "Units": self.units,
            "Area": area,
            "Output format": fmt,
            "Multi-page output": self.page_mode,
            "Arcs & circles": on(self.fit_arcs),
            "Join polylines / splines": f"{on(self.join_polylines)} / "
                                        f"{on(self.join_splines)}",
            "Curve precision": self.curve_precision,
            "Solid fills as HATCH": on(self.hatches),
            "Hatch patterns as HATCH": on(self.hatch_patterns),
            "Dashed lines rebuilt": on(self.merge_dashes),
            "Ignore white/background fills": f"{on(self.ignore_white_fills)} / "
                                             f"{on(self.ignore_background_fills)}",
            "Text / MTEXT grouping": f"{on(self.text_entities)} / "
                                     f"{on(self.group_mtext)}",
            "Text height factor": f"{self.text_height_factor:g}",
            "AutoCAD SHX comments": on(self.shx_comments),
            "Dimensions (arrows / ticks)": f"{on(self.dimensions)} / "
                                           f"{on(self.tick_dimensions)}",
            "Leaders": on(self.leaders),
            "Native PDF layers": on(self.use_pdf_layers),
            "Layer naming": self.layer_mode,
            "Linetype recognition": on(self.recognize_linetypes),
            "Colours": "AutoCAD Color Index" if self.color_mode == "aci"
                       else "true colour",
            "Block detection": (
                f"on (min {self.block_min_repeats} repeats"
                f"{', rotated/mirrored copies' if self.block_rotations else ''})"
                if self.block_detection else "off"),
            "Scanned pages: tracing": (f"on ({self.raster_dpi} dpi)"
                                       if self.raster_mode else "off"),
            "Scanned pages: OCR": (f"on ({self.ocr_engine}, {self.ocr_lang}"
                                   f"{', vertical' if self.ocr_vertical else ''})"
                                   if self.ocr else "off"),
            "Raster images": on(self.include_images),
            "Engine version": APP_VERSION,
        }


def normalize_rect(rect) -> Optional[List[float]]:
    """[x0, y0, x1, y1] with x0 < x1 and y0 < y1, or None when unusable."""
    if not rect:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in rect)
    except (TypeError, ValueError):
        return None
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:            # smaller than 1 pt: ignore
        return None
    return [x0, y0, x1, y1]
