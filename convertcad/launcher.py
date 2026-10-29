"""
launcher.py — friendly start-up checks when running FROM THE SOURCE CODE.

Uses the standard library only, so it works even when nothing else is
installed. It solves the two classic "nothing happens" situations:

  * the libraries are not installed yet (PySide6, PyMuPDF, ...): Python stops
    with ModuleNotFoundError and, when the file was double-clicked, the black
    window closes before anyone can read the message;
  * the command-line tool is double-clicked without arguments: it prints its
    usage and closes immediately.

ensure_dependencies() detects missing libraries and offers to install them
(pip, from requirements.txt). pause_if_double_clicked() keeps the window open
so the message can be read. None of this runs in the portable .exe, where
every library is already bundled.
"""

import importlib.util
import os
import subprocess
import sys

MIN_PYTHON = (3, 10)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

# import name -> pip package name
ENGINE_PACKAGES = {
    "pymupdf": "PyMuPDF",
    "ezdxf": "ezdxf",
    "numpy": "numpy",
    "cv2": "opencv-python-headless",
    "rapidocr": "rapidocr",            # OCR (built-in PP-OCR model)
    "onnxruntime": "onnxruntime",      # runs the OCR models
    "bidi": "python-bidi",             # Arabic OCR: right-to-left order
}
GUI_PACKAGES = {"PySide6": "PySide6-Essentials"}


def missing_packages(gui: bool = True) -> list:
    """pip names of the required libraries that cannot be imported."""
    wanted = dict(ENGINE_PACKAGES)
    if gui:
        wanted.update(GUI_PACKAGES)
    out = []
    for module, pip_name in wanted.items():
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(pip_name)
    return out


def has_console() -> bool:
    """False under pythonw.exe (double-clicked .pyw): no window to print to."""
    return sys.stdout is not None and sys.stdin is not None


def started_by_double_click() -> bool:
    """Windows: True when this process owns its console window, i.e. the
    script was double-clicked in Explorer (the window closes at exit)."""
    if os.name != "nt" or not has_console():
        return False
    if "PROMPT" in os.environ or "TERM_PROGRAM" in os.environ:
        return False                    # started from cmd.exe or VS Code
    try:
        import ctypes
        buf = (ctypes.c_uint * 8)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buf, 8)
        return count <= 2               # python (+ the py.exe launcher)
    except Exception:
        return False


def pause_if_double_clicked(text: str = "Press Enter to close this window.") -> None:
    if started_by_double_click():
        try:
            input("\n" + text)
        except (EOFError, KeyboardInterrupt):
            pass


def _message_box(title: str, text: str, ask: bool = False) -> bool:
    """Small dialog with tkinter (part of Python on Windows)."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        if ask:
            result = messagebox.askyesno(title, text)
        else:
            messagebox.showinfo(title, text)
            result = True
        root.destroy()
        return bool(result)
    except Exception:
        return False


def _say(title: str, text: str) -> None:
    """Print in the console, or show a dialog when there is none."""
    if has_console():
        print(text)
    else:
        _message_box(title, text)


def _pip_install() -> bool:
    """Install requirements.txt with the current Python. True on success."""
    python = sys.executable
    flags = 0
    if not has_console():
        # pythonw: run pip in a visible console so progress can be followed
        candidate = os.path.join(os.path.dirname(python), "python.exe")
        python = candidate if os.path.isfile(candidate) else python
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    cmd = [python, "-m", "pip", "install", "-r", REQUIREMENTS]
    if has_console():
        print("\n> " + " ".join(cmd) + "\n", flush=True)
    try:
        return subprocess.call(cmd, creationflags=flags) == 0
    except OSError:
        return False


def ensure_dependencies(gui: bool = True) -> bool:
    """Check Python and the libraries; offer to install what is missing.
    Returns True when everything is ready."""
    title = "ConvertCAD"
    if sys.version_info < MIN_PYTHON:
        text = (f"ConvertCAD needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or "
                f"newer; this is Python {sys.version.split()[0]}.\n"
                f"Install a recent Python from https://www.python.org/downloads/")
        _say(title, text)
        return False
    missing = missing_packages(gui)
    if not missing:
        return True
    text = ("ConvertCAD cannot start yet: these libraries are not installed "
            "for this Python:\n    " + ", ".join(missing) +
            f"\n\nPython used: {sys.executable}\n\n"
            "They can be installed now from requirements.txt (internet "
            "connection needed, a few minutes the first time).")
    if has_console():
        print(text)
        if not sys.stdin.isatty():
            print("\nInstall them with:\n    python -m pip install -r "
                  "requirements.txt")
            return False
        try:
            answer = input("\nInstall them now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer not in ("", "y", "yes", "o", "oui"):
            print("\nTo install later:  python -m pip install -r "
                  "requirements.txt\n(or run scripts\\setup_venv.bat)")
            return False
    elif not _message_box(title, text + "\n\nInstall them now?", ask=True):
        return False
    if not _pip_install() or missing_packages(gui):
        fail = ("The installation did not complete. Open a command prompt in "
                "the ConvertCAD folder and run:\n    python -m pip install -r "
                "requirements.txt\nto see the error.")
        _say(title, fail)
        return False
    if has_console():
        print("\nAll libraries installed.\n")
    return True
