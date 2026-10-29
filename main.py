"""
ConvertCAD launcher.

    python main.py            -> opens the application
    python main.py plan.pdf   -> opens the application with a drawing

This file is also the entry point of the portable .exe (see ConvertCAD.spec).
Imports stay INSIDE main(): the conversion runs in a child process that
re-imports this file, and it must not load the whole interface for nothing.

When run from the source code, convertcad/launcher.py first checks that the
libraries are installed (and offers to install them), so a double-click never
ends in a window that flashes and disappears.
"""

import os
import time

os.environ.setdefault("CONVERTCAD_T0", repr(time.time()))   # start-up timing

import multiprocessing  # noqa: E402
import sys  # noqa: E402


def main() -> int:
    multiprocessing.freeze_support()          # required by the .exe build
    frozen = getattr(sys, "frozen", False)    # True inside ConvertCAD.exe
    if not frozen:
        from convertcad.launcher import (ensure_dependencies,
                                         pause_if_double_clicked)
        if not ensure_dependencies(gui=True):
            pause_if_double_clicked()
            return 1
    try:
        from convertcad.ui.app import run_gui
        return run_gui(sys.argv[1:])
    except Exception:
        if frozen:
            raise
        import traceback
        traceback.print_exc()
        from convertcad.launcher import pause_if_double_clicked
        pause_if_double_clicked()
        return 1


if __name__ == "__main__":
    sys.exit(main())
