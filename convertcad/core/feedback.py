"""
feedback.py — the address of the "Report a problem / suggest an improvement"
form.

The form is hosted on Tally (tally.so), so users need no account. The
program only OPENS it in the web browser: nothing is sent by ConvertCAD.
Three hidden fields of the form are filled from the address itself, so the
user does not have to type them (and can see them in the address bar):

    version   ConvertCAD version, e.g. 1.2.2
    os        Windows / Linux / macOS
    lang      interface language, e.g. fr

To change the form, replace FORM_URL with the "Share" link of the Tally form.
While FORM_URL is empty, the GitHub "new issue" page is opened instead.
"""

import platform
from urllib.parse import urlencode

from .. import APP_VERSION
from .updates import REPOSITORY

FORM_URL = "https://tally.so/r/RWx889"
FALLBACK_URL = f"https://github.com/{REPOSITORY}/issues/new"


def _os_name() -> str:
    name = platform.system()
    return {"Darwin": "macOS"}.get(name, name or "Unknown")


def form_url(lang: str = "en", base: str = None) -> str:
    """Address to open: the Tally form with its hidden fields filled."""
    base = FORM_URL if base is None else base
    if not base:
        return FALLBACK_URL
    query = urlencode({"version": APP_VERSION, "os": _os_name(),
                       "lang": lang or "en"})
    return base + ("&" if "?" in base else "?") + query
