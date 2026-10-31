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
                        DWG_DXF_VERSION, LAYER_MODES, OCR_QUALITIES,
                        OUTPUT_FORMATS, UNITS)
from .ocr_catalog import language_set
from .units import effective_denominator


def _english(text: str, **kwargs) -> str:
    """No translation (conversion log): fill the {placeholders} only."""
    return text.format(**kwargs) if kwargs else text


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
    ocr_lang: str = "latin"                # OCR languages: latin, arabic,
                                           # latin+arabic… (ocr_catalog.py)
    ocr_quality: str = "standard"          # standard (built-in model) |
                                           # maximum (downloaded models)
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
        data = dict(data or {})
        # version 1.0: the "Maximum" OCR engine became the maximum accuracy
        if data.get("ocr_engine") == "paddleocr" and \
                "ocr_quality" not in data:
            data["ocr_quality"] = "maximum"
        clean = {k: v for k, v in data.items() if k in known}
        opt = cls(**clean)
        if opt.curve_precision not in CURVE_PRECISION:
            opt.curve_precision = "normal"
        opt.ocr_lang = language_set(opt.ocr_lang).key    # 1.0 codes too
        if opt.ocr_quality not in OCR_QUALITIES:
            opt.ocr_quality = "standard"
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

    def scale_text(self, t=None) -> str:
        t = t or _english
        if self.calibrated_units_per_pt > 0:
            den = effective_denominator(self.calibrated_units_per_pt,
                                        self.units)
            return t("calibrated ({value} {unit}/pt, about 1:{den})",
                     value=f"{self.calibrated_units_per_pt:.6g}",
                     unit=self.units, den=f"{den:.4g}")
        if self.auto_scale:
            return t("read on each sheet (1:{den} when none is written)",
                     den=f"{self.scale_denominator:g}")
        return f"1:{self.scale_denominator:g}"

    def describe(self, t=None) -> dict:
        """Options as shown in the report. Without `t` (a translation
        function such as the interface's tr) the text is English, as written
        in the conversion log."""
        t = t or _english
        on = lambda b: t("on") if b else t("off")                # noqa: E731
        area = t("whole sheet")
        if self.clip_rect:
            x0, y0, x1, y1 = self.clip_rect
            area = t("selected area {w} x {h} pt at ({x}, {y})",
                     w=f"{x1 - x0:.0f}", h=f"{y1 - y0:.0f}",
                     x=f"{x0:.0f}", y=f"{y0:.0f}")
        fmt = (t("DWG (AutoCAD 2000 format)") if self.output_format == "dwg"
               else f"DXF {self.dxf_version}")
        pages = {"single": t("One DXF, sheets side by side"),
                 "split": t("One DXF per sheet")}.get(self.page_mode,
                                                     self.page_mode)
        precision = {"fine": t("Fine"), "normal": t("Normal"),
                     "loose": t("Loose")}.get(self.curve_precision,
                                              self.curve_precision)
        unit = t(UNITS[self.units]["label"]) if self.units in UNITS \
            else self.units
        if self.block_detection:
            blocks = (t("on (at least {n} copies, also turned or mirrored)",
                        n=self.block_min_repeats) if self.block_rotations
                      else t("on (at least {n} copies)",
                             n=self.block_min_repeats))
        else:
            blocks = t("off")
        quality = t(OCR_QUALITIES.get(self.ocr_quality, self.ocr_quality))
        return {
            t("Scale"): self.scale_text(t),
            t("Units"): unit,
            t("Area"): area,
            t("Output format"): fmt,
            t("Multi-page output"): pages,
            t("Arcs and circles"): on(self.fit_arcs),
            t("Join polylines / splines"): f"{on(self.join_polylines)} / "
                                           f"{on(self.join_splines)}",
            t("Curve precision"): precision,
            t("Solid fills as HATCH"): on(self.hatches),
            t("Hatch patterns as HATCH"): on(self.hatch_patterns),
            t("Dashed lines rebuilt"): on(self.merge_dashes),
            t("Ignore white / background fills"):
                f"{on(self.ignore_white_fills)} / "
                f"{on(self.ignore_background_fills)}",
            t("Text / MTEXT grouping"): f"{on(self.text_entities)} / "
                                        f"{on(self.group_mtext)}",
            t("Text height ratio"): f"{self.text_height_factor:g}",
            t("AutoCAD SHX comments"): on(self.shx_comments),
            t("Dimensions (arrows / ticks)"): f"{on(self.dimensions)} / "
                                              f"{on(self.tick_dimensions)}",
            t("Leaders"): on(self.leaders),
            t("Native PDF layers"): on(self.use_pdf_layers),
            t("Layer naming"): t(LAYER_MODES.get(self.layer_mode,
                                                 self.layer_mode)),
            t("Linetype recognition"): on(self.recognize_linetypes),
            t("Colours"): t("AutoCAD Color Index") if self.color_mode == "aci"
                         else t("True colour (exact RGB)"),
            t("Block detection"): blocks,
            t("Scanned pages: tracing"): (t("on ({dpi} dpi)",
                                            dpi=self.raster_dpi)
                                          if self.raster_mode else t("off")),
            t("Scanned pages: OCR"): (
                t("on ({languages}, {quality})",
                  languages=t(language_set(self.ocr_lang).label),
                  quality=quality) if self.ocr else t("off")),
            t("Raster images"): on(self.include_images),
            t("Engine version"): APP_VERSION,
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
