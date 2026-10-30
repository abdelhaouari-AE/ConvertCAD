"""
app.py — starts the desktop application.

  * crisp rendering on every Windows display scaling (Qt 6 is DPI-aware;
    fractional factors such as 125 % / 150 % are passed through unrounded)
  * theme and language from the user settings
  * first-launch Terms of use
  * crash safety: unexpected errors are written to
    <settings folder>/convertcad.log and shown in a readable dialog
  * fast start: the window appears first; the conversion libraries
    (PyMuPDF, ezdxf, NumPy) are then loaded in the background ("warm-up"),
    so they are ready when the first drawing is opened

Developer tool: set CONVERTCAD_STARTUP_PROBE=1 to print how long the window
took to appear, then quit (used to measure start-up time).
"""

import faulthandler
import logging
import os
import sys
import threading
import time
import traceback

from .. import APP_NAME, APP_VERSION
from ..config import Settings, log_path, settings_dir


def _setup_logging() -> None:
    os.makedirs(settings_dir(), exist_ok=True)
    logging.basicConfig(filename=log_path(), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # a windowed .exe has no console: keep stray prints from failing
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    try:
        faulthandler.enable(open(log_path(), "a"))     # native crashes
    except Exception:                                   # pragma: no cover
        pass


def _warm_up() -> None:
    """Import the heavy libraries in a background thread, after the window
    is on screen. Opening the first PDF is then instant."""
    def work():
        try:
            import numpy  # noqa: F401
            from ..core import compat  # noqa: F401  (PyMuPDF)
            from ..core import pdfinfo  # noqa: F401
            import ezdxf  # noqa: F401
            from ..core import postprocess  # noqa: F401
            logging.info("warm-up done")
        except Exception:                                  # pragma: no cover
            logging.exception("warm-up failed")
    threading.Thread(target=work, name="convertcad-warm-up",
                     daemon=True).start()


def _startup_probe(app) -> None:
    t0 = float(os.environ.get("CONVERTCAD_T0", "0") or 0)
    elapsed = time.time() - t0 if t0 else -1.0
    heavy = [m for m in ("fitz", "pymupdf", "ezdxf", "numpy", "cv2")
             if m in sys.modules]
    print(f"STARTUP {elapsed:.3f} s; heavy modules loaded before the window: "
          f"{', '.join(heavy) or 'none'}", flush=True)
    app.quit()


def run_gui(argv=None) -> int:
    argv = list(argv or [])
    _setup_logging()
    logging.info("%s %s starting", APP_NAME, APP_VERSION)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)

    settings = Settings.load()
    from ..i18n import is_rtl, set_language, tr
    set_language(settings.language)
    if is_rtl():                       # Arabic: the interface right to left
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    from . import theme
    theme.apply_theme(app, settings.theme)
    from .icons import app_icon
    app.setWindowIcon(app_icon())

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        logging.error(text)
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, APP_NAME,
                              tr("An unexpected error occurred") + "\n\n"
                              + f"{etype.__name__}: {value}\n\n"
                              + tr("Details were written to {path}.",
                                   path=log_path()))
            box.setDetailedText(text)
            box.exec()
        except Exception:                               # pragma: no cover
            pass

    sys.excepthook = excepthook

    if not settings.terms_accepted:
        from .dialogs import TermsDialog
        if TermsDialog(gate=True).exec() != TermsDialog.DialogCode.Accepted:
            return 0
        settings.terms_accepted = True
        settings.save()

    from .main_window import MainWindow
    win = MainWindow(settings)
    win.show()
    from PySide6.QtCore import QTimer
    if os.environ.get("CONVERTCAD_STARTUP_PROBE"):
        QTimer.singleShot(0, lambda: _startup_probe(app))
    else:
        QTimer.singleShot(300, _warm_up)
    pdfs = [a for a in argv if a.lower().endswith(".pdf") and os.path.isfile(a)]
    if pdfs:
        QTimer.singleShot(0, lambda: win.open_pdf(os.path.abspath(pdfs[0])))
    return app.exec()
