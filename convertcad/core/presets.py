"""
presets.py — ready-made option sets for typical drawings.

A preset only lists the options it CHANGES from the defaults. Built-in
presets never touch the drawing-specific values (scale, units, pages,
calibration). Users can save their own presets from the interface; those
are stored in the settings file and may include a scale.
"""

from typing import Dict

from .options import Options

# keys never stored in / applied from a preset
DRAWING_SPECIFIC = ("pages", "calibrated_units_per_pt", "clip_rect")

BUILTIN_PRESETS: Dict[str, Dict] = {
    "recommended": {
        "label": "Recommended (all features)",
        "options": {},
    },
    "architectural": {
        "label": "Architectural plans (tick dimensions)",
        "options": {"tick_dimensions": True, "dimensions": True,
                    "group_mtext": True, "layer_mode": "style",
                    "block_min_repeats": 2},
    },
    "structural": {
        "label": "Structural / formwork plans",
        "options": {"dimensions": True, "tick_dimensions": True,
                    "recognize_linetypes": True, "block_min_repeats": 3},
    },
    "scanned": {
        "label": "Scanned archive drawings (OCR)",
        "options": {"raster_mode": True, "ocr": True, "ocr_vertical": True,
                    "raster_dpi": 400, "block_detection": False,
                    "use_pdf_text_layer": True},
    },
    "geometry": {
        "label": "Geometry only (no annotations)",
        "options": {"dimensions": False, "tick_dimensions": False,
                    "leaders": False, "block_detection": False,
                    "group_mtext": False},
    },
    "cnc": {
        "label": "CNC / laser (R12, single layer, no text)",
        "options": {"dxf_version": "R12", "layer_mode": "single",
                    "use_pdf_layers": False, "text_entities": False,
                    "hatches": False, "dimensions": False,
                    "tick_dimensions": False, "leaders": False,
                    "block_detection": False, "include_images": False,
                    "shx_comments": False, "join_splines": True,
                    "hatch_patterns": False, "output_format": "dxf"},
    },
}


def apply_preset(current: Options, preset_options: Dict,
                 builtin: bool = True) -> Options:
    """New Options = defaults + preset, keeping drawing-specific values
    (and, for built-in presets, the scale and units) from `current`."""
    data = Options().to_dict()
    data.update({k: v for k, v in preset_options.items()
                 if k not in DRAWING_SPECIFIC})
    keep = list(DRAWING_SPECIFIC)
    if builtin:
        keep += ["scale_denominator", "units", "auto_scale"]
    cur = current.to_dict()
    for k in keep:
        data[k] = cur[k]
    return Options.from_dict(data)


def preset_from_options(opt: Options) -> Dict:
    """What a user preset stores (everything except drawing specifics)."""
    return {k: v for k, v in opt.to_dict().items()
            if k not in DRAWING_SPECIFIC}
