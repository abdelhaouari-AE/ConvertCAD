"""
updates.py — optional check for a newer ConvertCAD. OFF by default.

It runs only when the user asks (Help > Check for updates…) or has switched
on "Check for updates at startup". It makes ONE request to GitHub's public
API for the latest ConvertCAD release:
  * nothing is sent — no drawing, no file name, no identifier; the request
    only says "ConvertCAD/<version>" (its User-Agent);
  * nothing is downloaded or installed: when a newer version exists the
    program shows its number and, if the user wants, opens the release
    page in the browser.
Any failure (no internet, proxy, GitHub unreachable) is reported, never
fatal.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Tuple

from .ocr_store import _ssl_context, _user_agent

REPOSITORY = "abdelhaouari-AE/ConvertCAD"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
TIMEOUT_S = 10


class UpdateError(Exception):
    """The latest version could not be read (message for the user)."""


@dataclass
class UpdateInfo:
    current: str
    latest: str
    url: str                     # release page

    @property
    def newer(self) -> bool:
        return is_newer(self.latest, self.current)


def parse_version(text: str) -> Tuple[int, ...]:
    """'v1.2.0' -> (1, 2, 0); anything after the numbers is ignored."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return bool(a) and a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def check(current: str = "") -> UpdateInfo:
    """Ask GitHub for the latest release (one request, nothing sent)."""
    if not current:
        from .. import APP_VERSION
        current = APP_VERSION
    req = urllib.request.Request(LATEST_API, headers={
        "User-Agent": _user_agent(), "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                    context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no published release was found") from exc
        raise UpdateError(f"GitHub answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"GitHub could not be reached ({reason})") from exc
    tag = str(data.get("tag_name") or data.get("name") or "")
    if not parse_version(tag):
        raise UpdateError("the latest release has no version number")
    latest = ".".join(str(x) for x in parse_version(tag))
    return UpdateInfo(current=current, latest=latest,
                      url=str(data.get("html_url") or RELEASES_PAGE))
