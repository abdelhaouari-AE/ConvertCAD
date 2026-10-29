"""
constants.py — units, scales, DXF versions and reserved layer names.

Everything here is plain data shared by the engine, the interface and the
command-line tool. Change a value here and every part of the app follows.
"""

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
# The PDF native unit is the point: 1 pt = 1/72 inch = 25.4/72 mm on paper.
PT_TO_MM = 25.4 / 72.0

# Drawing units offered for the DXF. "factor" converts millimetres to the
# unit; "insunits" is the DXF header code ($INSUNITS) read by CAD software.
UNITS = {
    "mm": {"factor": 1.0, "insunits": 4, "label": "Millimetres (mm)"},
    "cm": {"factor": 0.1, "insunits": 5, "label": "Centimetres (cm)"},
    "m": {"factor": 0.001, "insunits": 6, "label": "Metres (m)"},
}
DEFAULT_UNITS = "mm"

# Paper scales proposed in the interface (denominator N of 1:N). The field
# stays editable, so any custom scale such as 1:75 can be typed.
PAPER_SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 200, 250, 500,
                1000, 2000, 2500, 5000]

# ---------------------------------------------------------------------------
# DXF versions (label shown to the user -> ezdxf identifier)
# ---------------------------------------------------------------------------
DXF_VERSIONS = {
    "R2018": "AutoCAD 2018 and later",
    "R2013": "AutoCAD 2013",
    "R2010": "AutoCAD 2010",
    "R2007": "AutoCAD 2007",
    "R2004": "AutoCAD 2004",
    "R2000": "AutoCAD 2000",
    "R12": "AutoCAD R12, legacy and CNC",
}
DEFAULT_DXF_VERSION = "R2018"

# ---------------------------------------------------------------------------
# Reserved "role" layers (created on demand by the writer)
# ---------------------------------------------------------------------------
LAYER_TEXT = "TEXT"
LAYER_SHX_TEXT = "TEXT_SHX"         # AutoCAD SHX comments recovered as text
LAYER_SHX_STROKES = "TEXT_SHX_STROKES"  # their letter strokes (layer off)
LAYER_HATCH = "HATCH"
LAYER_IMAGE = "IMG_RASTER"          # locked: scanned content kept for checking
LAYER_DIM = "DIM"                   # true reconstructed DIMENSION entities
LAYER_DIM_RAW = "DIM_RAW"           # measurement texts that matched no dimension
LAYER_LEADER = "ANNOT_LEADER"
LAYER_BLOCKS = "BLOCKS"             # block references (INSERT)
LAYER_TRACE = "TRACE_LINES"         # geometry traced from scanned pages
LAYER_TRACE_TEXT = "TRACE_TEXT"     # OCR text from scanned pages
LAYER_SINGLE = "GEOMETRY"           # used by the "single layer" naming mode
LAYER_DEFAULT = "GEO"

ROLE_LAYERS = (LAYER_TEXT, LAYER_SHX_TEXT, LAYER_SHX_STROKES, LAYER_HATCH,
               LAYER_IMAGE,
               LAYER_DIM, LAYER_DIM_RAW, LAYER_LEADER, LAYER_BLOCKS,
               LAYER_TRACE, LAYER_TRACE_TEXT)

# Layer naming strategies for geometry (see layers.py)
LAYER_MODES = {
    "style": "Colour + lineweight + linetype",
    "color": "Colour only",
    "single": "Single geometry layer",
}
DEFAULT_LAYER_MODE = "style"

# Multi-page output strategies (see pipeline.py)
PAGE_MODES = {
    "single": "One DXF, pages side by side",
    "split": "One DXF per page",
}
DEFAULT_PAGE_MODE = "single"

# Curve-fitting precision presets (multiplier applied to geometry.Tol)
CURVE_PRECISION = {"fine": 0.5, "normal": 1.0, "loose": 2.0}

# OCR languages offered (Tesseract codes). Languages need their traineddata.
OCR_LANGUAGES = ["eng+fra", "fra", "eng", "eng+fra+ara", "ara"]

# OCR engines (see core/ocr.py). "auto" = the best engine available.
OCR_ENGINES = {
    "auto": "Automatic (best available)",
    "tesseract": "Fast — Tesseract",
    "rapidocr": "Accurate — RapidOCR",
    "paddleocr": "Maximum — PaddleOCR",
}

# Output file formats. DWG is written by the bundled GNU LibreDWG converter
# from an AutoCAD 2000 DXF (the DWG version LibreDWG writes).
OUTPUT_FORMATS = {
    "dxf": "DXF drawing",
    "dwg": "DWG drawing (AutoCAD 2000 format)",
}
DWG_DXF_VERSION = "R2000"

# Scan resolutions offered for raster tracing (dpi)
RASTER_DPI_CHOICES = [200, 300, 400, 600]
MAX_RASTER_PIXELS = 220_000_000     # safety cap: higher dpi is reduced
