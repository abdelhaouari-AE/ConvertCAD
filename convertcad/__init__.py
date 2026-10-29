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

APP_NAME = "ConvertCAD"
APP_VERSION = "1.0.0"
APP_AUTHOR = "abdelhaouari"
APP_YEAR = "2026"
APP_DESCRIPTION = "PDF 2D drawings to editable DXF converter"

__version__ = APP_VERSION
__all__ = ["APP_NAME", "APP_VERSION", "APP_AUTHOR", "APP_YEAR",
           "APP_DESCRIPTION", "__version__"]
