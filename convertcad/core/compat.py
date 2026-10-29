"""
compat.py — one import point for PyMuPDF.

PyMuPDF is imported as ``pymupdf`` since version 1.24.3; the historic name
``fitz`` is deprecated (PyMuPDF 2.x prints a FutureWarning). Every module of
ConvertCAD imports ``pymupdf`` from here, so a future API change is handled
in ONE place.

Also provides ``page_matrix()``: PyMuPDF returns vector paths and text in
UNROTATED page coordinates, while the user sees (and the preview renders) the
ROTATED page. Applying this matrix makes the DXF match what is displayed.

PyMuPDF 2.x tries to import two optional add-ons when it starts:
``pymupdf.layout`` (ONNX page-layout models, about 0.5 s to load) and
``pymupdf4llm`` (Markdown export for AI tools). ConvertCAD uses neither, so they
are blocked below: every start of the application — and every conversion
process — is about 0.6 s faster, and the portable build stays smaller.
"""

import os
import sys
import warnings

for _optional in ("pymupdf.layout", "pymupdf4llm"):
    sys.modules.setdefault(_optional, None)    # "import" now fails instantly;
                                               # PyMuPDF catches ImportError
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")   # no advert

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import pymupdf  # noqa: F401  (PyMuPDF >= 1.24.3)
    except ImportError:                                  # pragma: no cover
        import fitz as pymupdf  # noqa: F401  (older PyMuPDF)


def page_matrix(page) -> "pymupdf.Matrix":
    """Matrix mapping unrotated page coordinates to displayed coordinates."""
    if page.rotation % 360:
        return page.rotation_matrix
    return pymupdf.Identity


def transform_point(m, x: float, y: float):
    """Apply a pymupdf.Matrix to a point -> (x, y) tuple."""
    return (m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f)


def transform_vector(m, dx: float, dy: float):
    """Apply only the linear part of a matrix (for directions)."""
    return (m.a * dx + m.c * dy, m.b * dx + m.d * dy)


def library_versions() -> dict:
    """Versions of the main libraries, for the About box and the log."""
    out = {"PyMuPDF": getattr(pymupdf, "VersionBind", "?")}
    # (OCR engines and the DWG converter: see ocr.py / dwg.py)
    for name, mod in (("ezdxf", "ezdxf"), ("NumPy", "numpy"),
                      ("OpenCV", "cv2")):
        try:
            m = __import__(mod)
            out[name] = getattr(m, "__version__", "?")
        except Exception:                                 # pragma: no cover
            out[name] = "not installed"
    return out
