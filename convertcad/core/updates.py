"""
updates.py — optional check for a newer ConvertCAD. OFF by default.

It runs only when the user asks (Help > Check for updates…) or has switched
on "Check for updates at startup". It makes ONE request to GitHub's public
API for the list of ConvertCAD releases:
  * nothing is sent — no drawing, no file name, no identifier; the request
    only says "ConvertCAD/<version>" (its User-Agent);
  * nothing is downloaded or installed: when a newer version exists the
    program shows its number and, if the user wants, opens the release
    page in the browser.
Any failure (no internet, proxy, GitHub unreachable) is reported, never
fatal.

Why the list and not GitHub's "latest release": the repository also
publishes the OCR models as a release ("ocr-models-v1"). GitHub may call
that one the latest, so the program picks the highest version tag itself.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from .ocr_store import _ssl_context, _user_agent

REPOSITORY = "abdelhaouari-AE/ConvertCAD"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
TIMEOUT_S = 10

# A program release is tagged with its version: "v1.2.0" (or "1.2.0").
# Other releases of the repository ("ocr-models-v1") do not match.
_VERSION_TAG = re.compile(r"^v?\d+(?:\.\d+)+$")


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


def _sort_key(tag: str) -> Tuple[int, ...]:
    """Version numbers padded to the same length: 1.2 sorts like 1.2.0."""
    v = parse_version(tag)
    return v + (0,) * max(0, 4 - len(v))


def newest_release(releases) -> Optional[dict]:
    """The published program release with the highest version number.
    Skipped: drafts, pre-releases and releases that are not a program
    version (the OCR models, "ocr-models-v1"). None when there is none."""
    best = None
    for rel in releases if isinstance(releases, list) else []:
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        tag = str(rel.get("tag_name") or "").strip()
        if not _VERSION_TAG.match(tag):
            continue
        if best is None or _sort_key(tag) > _sort_key(best["tag_name"]):
            best = rel
    return best


def check(current: str = "") -> UpdateInfo:
    """Ask GitHub for the releases (one request, nothing sent) and return
    the newest program version."""
    if not current:
        from .. import APP_VERSION
        current = APP_VERSION
    req = urllib.request.Request(RELEASES_API, headers={
        "User-Agent": _user_agent(), "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                    context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:              # no repository (or a private one)
            raise UpdateError("no published release was found") from exc
        raise UpdateError(f"GitHub answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"GitHub could not be reached ({reason})") from exc
    rel = newest_release(data)
    if rel is None:
        raise UpdateError("no published release was found")
    latest = ".".join(str(x) for x in parse_version(str(rel["tag_name"]).strip()))
    return UpdateInfo(current=current, latest=latest,
                      url=str(rel.get("html_url") or RELEASES_PAGE))
