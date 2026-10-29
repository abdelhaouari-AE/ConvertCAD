"""
ConvertCAD — convert 2D PDF drawings into editable DXF files built with
real CAD entities (lines, polylines, arcs, circles, splines, hatches, text,
true dimensions, leaders, layers and blocks).

Package layout
--------------
convertcad/
    core/        conversion engine — pure Python, never imports Qt
    ui/          desktop interface (PySide6 / Qt 6)
    resources/   user guide, terms of use, OCR help (bundled in the .exe)
    cli.py       command-line interface (batch scripts, automation)
    config.py    user settings persistence (JSON in the user profile)
    i18n.py      English / French interface strings

The version number lives HERE ONLY. The interface, the conversion log, the
About box and the build scripts all read it from this module.
"""

import os as _os

# Privacy: ONNX Runtime (which runs the OCR models) records usage data — the
# program path, operating system, processor… — and uploads it to Microsoft
# (seen on Linux too, with version 1.31). ConvertCAD sends nothing anywhere, so
# this is switched off here, before any part of ConvertCAD can load ONNX
# Runtime: the setting is read when the library is imported, and the
# conversion processes started by the interface inherit it.
_os.environ["ORT_DISABLE_TELEMETRY"] = "1"

APP_NAME = "ConvertCAD"
APP_VERSION = "1.1.1"
APP_AUTHOR = "abdelhaouari"
APP_YEAR = "2026"
APP_DESCRIPTION = "PDF 2D drawings to editable DXF converter"

__version__ = APP_VERSION
__all__ = ["APP_NAME", "APP_VERSION", "APP_AUTHOR", "APP_YEAR",
           "APP_DESCRIPTION", "__version__"]
