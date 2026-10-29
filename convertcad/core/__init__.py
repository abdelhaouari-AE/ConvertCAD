"""
convertcad.core — the conversion engine.

Pure Python: PyMuPDF (PDF reading), NumPy (geometry), ezdxf (DXF writing),
OpenCV + OCR engines (scanned pages), GNU LibreDWG (DWG output). It NEVER
imports the Qt interface, so it can run in a background process, in the
command-line tool and in tests.

Public API:
    from convertcad.core import Options, convert, convert_folder
    report = convert("plan.pdf", "plan.dxf", Options(scale_denominator=100))
    print(report.render())

Start-up speed: the names below are loaded LAZILY (PEP 562 module
__getattr__). Importing a light module such as convertcad.core.constants
no longer drags PyMuPDF, NumPy and ezdxf into memory; they load the first
time convert() & co. are actually used.
"""

from importlib import import_module

_LAZY = {
    "Options": ".options",
    "convert": ".pipeline",
    "convert_folder": ".pipeline",
    "Cancelled": ".pipeline",
    "find_pdfs": ".paths",
    "ConversionReport": ".report",
}

__all__ = sorted(_LAZY)


def __getattr__(name):                      # called only for missing names
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value                 # next access is a plain lookup
    return value
