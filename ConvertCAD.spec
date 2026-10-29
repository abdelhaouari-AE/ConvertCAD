# -*- mode: python ; coding: utf-8 -*-
"""
ConvertCAD.spec — PyInstaller recipe for the portable application.

Build (from the repository root, ideally with scripts\\build_exe.bat):

    pyinstaller --noconfirm --clean ConvertCAD.spec

Output:
    default               dist/ConvertCAD/ConvertCAD.exe      (folder: fast
                          dist/ConvertCAD/ConvertCAD-cli.exe   start) + the
                                                               console tool
    CONVERTCAD_ONEFILE=1  dist/ConvertCAD.exe                 (single file:
                                                               easy to carry,
                                                               slower start)

Nothing is installed on the target computer: copy the folder (or the single
exe) anywhere — USB stick included — and run it. No admin rights needed.

Bundled with the program (no separate installation for the user):
  * GNU LibreDWG (DWG output)     vendor/libredwg/win64 or linux-x86_64
  * RapidOCR + its PP-OCR models  the rapidocr / onnxruntime packages
  * larger OCR models (optional)  vendor/ocr_models (scripts/get_ocr_models.py)
  * Tesseract OCR (optional)      copied by scripts/build_exe.bat
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(SPECPATH)                    # noqa: F821 (PyInstaller)
sys.path.insert(0, ROOT)
from convertcad import APP_AUTHOR, APP_NAME, APP_VERSION, APP_YEAR  # noqa: E402

ONEFILE = os.environ.get("CONVERTCAD_ONEFILE", "0") == "1"
ICON = os.path.join(ROOT, "assets", "icon.ico")

# ---- files the program reads at run time ---------------------------------
datas = [(os.path.join(ROOT, "convertcad", "resources"), "convertcad/resources")]
datas += collect_data_files("ezdxf")                # ezdxf fonts / resources

# RapidOCR: its settings (config.yaml, default_models.yaml) and its PP-OCR
# models (models/*.onnx). The PyTorch network descriptions are not needed.
_RAPID_SKIP = ("pytorch", "paddle", "openvino", "tensorrt", "mnn")
datas += collect_data_files("rapidocr", excludes=["**/pytorch/**"])

# GNU LibreDWG (DWG output), already built for this platform:
#   Windows: vendor/libredwg/win64 (in the repository)
#   Linux:   vendor/libredwg/linux-x86_64 (scripts/build_libredwg.sh linux)
_LDWG = os.path.join(ROOT, "vendor", "libredwg",
                     "win64" if sys.platform == "win32" else "linux-x86_64")
_LDWG_EXE = "dxf2dwg.exe" if sys.platform == "win32" else "dxf2dwg"
if os.path.isfile(os.path.join(_LDWG, _LDWG_EXE)):
    for name in sorted(os.listdir(_LDWG)):
        datas.append((os.path.join(_LDWG, name), "libredwg"))
    for name in ("README.md", "SOURCE.txt"):
        datas.append((os.path.join(ROOT, "vendor", "libredwg", name),
                      "libredwg"))
else:
    print(f"WARNING: {_LDWG} not found - DWG output will be UNAVAILABLE in "
          f"this build (run scripts/build_libredwg.sh first).")

# Larger OCR models for "Maximum" + the Arabic model (optional download)
_MODELS = os.path.join(ROOT, "vendor", "ocr_models")
if os.path.isdir(_MODELS):
    for name in sorted(os.listdir(_MODELS)):
        if name.endswith((".onnx", ".txt")):
            datas.append((os.path.join(_MODELS, name), "ocr_models"))

# ---- modules PyInstaller cannot see (imported lazily) ----------------------
_ocr_modules = (
    collect_submodules("rapidocr",
                       filter=lambda n: not any(k in n for k in _RAPID_SKIP))
    + ["onnxruntime", "bidi", "bidi.algorithm", "pytesseract"])
hiddenimports = (collect_submodules("ezdxf.addons.drawing")
                 + _ocr_modules + ["PySide6.QtSvg"])

# ---- things ConvertCAD never uses -----------------------------------------
# Some libraries import these *optionally* (pytesseract -> pandas, ...): if
# they happen to be installed on the build machine they would be bundled
# for nothing (hundreds of MB). Build from a clean .venv anyway.
excludes = [
    "tkinter", "matplotlib", "IPython", "jedi", "pytest", "setuptools", "pip",
    "pandas", "scipy", "sklearn", "sympy", "torch", "torchvision",
    "tensorflow", "lxml", "chardet", "notebook", "jupyter_client",
    # optional HTTPS add-ons of requests / urllib3 (ConvertCAD never downloads)
    "cryptography", "OpenSSL",
    # other OCR back-ends: the .exe runs PP-OCR models with ONNX Runtime
    # (the PaddleOCR library itself is only used when running from source)
    "paddle", "paddleocr", "paddlex", "openvino", "tensorrt", "MNN",
    # PyMuPDF 2.x optional add-ons (blocked in convertcad/core/compat.py)
    "pymupdf.layout", "pymupdf4llm", "networkx", "tabulate",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtDesigner",
]
# Files dropped from the bundle (Windows), by name prefix:
#  - opengl32sw: Qt's software OpenGL fallback (~20 MB), not used by a widgets
#    application that draws with the raster engine;
#  - opencv_videoio_ffmpeg: OpenCV's video plugin (~25 MB), loaded only to read
#    video files - ConvertCAD only reads images.
DROP_PREFIXES = ("opengl32sw", "opencv_videoio_ffmpeg")
#  - Linux: Qt's GTK 3 "platform theme" plugin and the GTK libraries it pulls
#    in (~15 MB). A GTK copied from the build machine can clash with the
#    user's desktop; without it Qt uses its own dialogs (the app has its own
#    theme anyway). The X11 / Wayland / GLib libraries Qt needs are kept.
if sys.platform.startswith("linux"):
    DROP_PREFIXES += ("libqgtk3", "libgtk-3", "libgdk-3", "libgdk_pixbuf",
                      "libatk-1.0", "libatk-bridge", "libcairo", "libpango",
                      "libepoxy")

# ---- Windows file properties (right-click > Properties > Details) ---------
version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(x) for x in (APP_VERSION.split(".") + ["0"] * 4)[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", APP_AUTHOR),
                StringStruct("FileDescription",
                             f"{APP_NAME} - PDF to DXF converter"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", APP_NAME),
                StringStruct("LegalCopyright",
                             f"Copyright (c) {APP_YEAR} {APP_AUTHOR}"),
                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", APP_VERSION)])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ])

def _keep(entries):
    return [e for e in entries
            if not os.path.basename(e[0]).lower().startswith(DROP_PREFIXES)]


a = Analysis(                                        # noqa: F821
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
a.binaries = _keep(a.binaries)
pyz = PYZ(a.pure)                                    # noqa: F821

common = dict(
    name=APP_NAME,
    console=False,                # windowed application (no black console)
    icon=ICON if os.path.isfile(ICON) else None,
    version=version_info,
    upx=False,                    # UPX often triggers antivirus false alarms
    debug=False,
    strip=False,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],   # noqa: F821
              runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,  # noqa: F821
              **common)
    # Console twin for scripts / batch files: ConvertCAD-cli.exe, same
    # folder, same libraries (no Qt needed).
    a_cli = Analysis(                                # noqa: F821
        [os.path.join(ROOT, "convertcad_cli.py")],
        pathex=[ROOT],
        datas=datas,
        hiddenimports=_ocr_modules,
        excludes=excludes + ["PySide6", "shiboken6"],
        noarchive=False,
    )
    a_cli.binaries = _keep(a_cli.binaries)
    exe_cli = EXE(PYZ(a_cli.pure), a_cli.scripts, [],  # noqa: F821
                  exclude_binaries=True,
                  **dict(common, name=f"{APP_NAME}-cli", console=True))
    coll = COLLECT(exe, exe_cli,                     # noqa: F821
                   a.binaries, a.datas, a_cli.binaries, a_cli.datas,
                   name=APP_NAME, upx=False)
