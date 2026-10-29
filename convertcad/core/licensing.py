"""
licensing.py — license management HOOK.

ConvertCAD currently ships unrestricted: check_license() always passes.
The pipeline and the About box already call these two functions, so adding
real license management later (keys, expiry, machine binding, activation)
means replacing THIS FILE ONLY — nothing else in the codebase changes.

Keep these signatures stable:
    check_license()   -> (ok: bool, message: str)   # called before converting
    license_summary() -> str                         # shown in the About box
"""

from typing import Tuple


def check_license() -> Tuple[bool, str]:
    """Current version: always licensed."""
    return True, "Free version — no license required."


def license_summary() -> str:
    """One line for the About box (translated by the interface)."""
    return "Free software, GNU AGPL v3.0 — no activation required."
