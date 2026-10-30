"""
config.py — user settings, saved as JSON.

Location:
  * normally   : <user profile>/.convertcad/settings.json  (no admin rights)
  * portable   : next to ConvertCAD.exe when a file named
                 "ConvertCAD.portable" sits beside it (USB-stick use)

Everything is optional with safe defaults, so an old or damaged settings
file never prevents the application from starting.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List

APP_DIR_NAME = ".convertcad"
PORTABLE_MARKER = "ConvertCAD.portable"
MAX_RECENT = 12


def _exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def settings_dir() -> str:
    exe_dir = _exe_dir()
    if os.path.isfile(os.path.join(exe_dir, PORTABLE_MARKER)):
        return os.path.join(exe_dir, "settings")
    return os.path.join(os.path.expanduser("~"), APP_DIR_NAME)


def settings_path() -> str:
    return os.path.join(settings_dir(), "settings.json")


def log_path() -> str:
    """Diagnostic log of the application itself (not conversion logs)."""
    return os.path.join(settings_dir(), "convertcad.log")


@dataclass
class Settings:
    terms_accepted: bool = False
    theme: str = "dark"                       # dark | light
    language: str = "en"                      # en | fr
    recent_files: List[str] = field(default_factory=list)
    last_open_dir: str = ""
    last_save_dir: str = ""
    last_batch_in: str = ""
    last_batch_out: str = ""
    options: Dict = field(default_factory=dict)          # last used Options
    presets: Dict[str, Dict] = field(default_factory=dict)   # user presets
    snap_end: bool = True
    snap_mid: bool = True
    snap_int: bool = True
    snap_center: bool = True
    open_folder_after_save: bool = False
    show_activity: bool = True
    check_updates: bool = False               # opt-in: ask GitHub at startup
    window_geometry: str = ""                 # base64 (Qt saveGeometry)
    window_state: str = ""                    # base64 (Qt saveState)

    # ---------------------------------------------------------------------
    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            with open(settings_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            known = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in known:
                    setattr(s, k, v)
        except Exception:
            pass
        # migrate the v1/v2 config file (terms acceptance)
        old = os.path.join(os.path.expanduser("~"), ".convertcad_config.json")
        if not s.terms_accepted and os.path.isfile(old):
            try:
                with open(old, "r", encoding="utf-8") as fh:
                    s.terms_accepted = bool(json.load(fh).get("terms_accepted"))
            except Exception:
                pass
        if s.theme not in ("dark", "light"):
            s.theme = "dark"
        if s.language not in ("en", "fr"):
            s.language = "en"
        return s

    def save(self) -> None:
        try:
            os.makedirs(settings_dir(), exist_ok=True)
            tmp = settings_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
            os.replace(tmp, settings_path())       # atomic: never half-written
        except Exception:
            pass                                    # never block the app

    def add_recent(self, path: str) -> None:
        path = os.path.normpath(path)
        self.recent_files = [p for p in self.recent_files
                             if os.path.normcase(p) != os.path.normcase(path)]
        self.recent_files.insert(0, path)
        del self.recent_files[MAX_RECENT:]

    def existing_recent(self) -> List[str]:
        return [p for p in self.recent_files if os.path.isfile(p)]
