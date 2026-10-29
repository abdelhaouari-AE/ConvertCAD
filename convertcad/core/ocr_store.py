"""
ocr_store.py — where the downloadable OCR models live, and how they get there.

Folder (the same logic for the portable program, the installers, the
AppImage, the .deb and the source code):

    portable mode (a file              <program folder>/ocr_models
    "ConvertCAD.portable" next to      (travels with the program, e.g. on
    the program)                       a USB stick)
    Windows                            %LOCALAPPDATA%\\ConvertCAD\\ocr_models
    Linux                              ~/.local/share/convertcad/ocr_models
    macOS                              ~/Library/Application Support/
                                       ConvertCAD/ocr_models
    environment variable               overrides all of the above
    CONVERTCAD_OCR_MODELS

The program folder itself is never written to (it is read-only in Program
Files, in an AppImage or in /opt). Models placed in an "ocr_models" folder
inside the program (an offline build) are found too.

Downloads: GitHub release first, RapidOCR's repository as a mirror; each
file is written to a temporary ".part" file, checked against its SHA-256
and only then renamed, so an interrupted or damaged download never leaves a
bad model behind. Nothing but the requested file is ever sent or received.

Standard library only (no Qt): used by the interface, the command line and
the build scripts.
"""

import functools
import hashlib
import os
import shutil
import ssl
import sys
import urllib.request
from typing import Callable, Dict, List, Optional

from .ocr_catalog import BY_ID, PACKS, ModelFile, OcrPack

PORTABLE_MARKER = "ConvertCAD.portable"
CHUNK = 256 * 1024
TIMEOUT_S = 30

ProgressFn = Callable[[int, int], None]       # bytes done, bytes total


class DownloadCancelled(Exception):
    pass


class DownloadError(Exception):
    pass


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
def _program_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def is_portable() -> bool:
    return os.path.isfile(os.path.join(_program_dir(), PORTABLE_MARKER))


def user_models_dir() -> str:
    """The folder where downloaded models are stored (may not exist yet)."""
    env = os.environ.get("CONVERTCAD_OCR_MODELS", "")
    if env:
        return env
    if is_portable():
        return os.path.join(_program_dir(), "ocr_models")
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            home, "AppData", "Local")
        return os.path.join(base, "ConvertCAD", "ocr_models")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support",
                            "ConvertCAD", "ocr_models")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        home, ".local", "share")
    return os.path.join(base, "convertcad", "ocr_models")


def search_dirs() -> List[str]:
    """Folders searched for model files, in order."""
    dirs = [user_models_dir(), os.path.join(_program_dir(), "ocr_models")]
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        dirs.append(os.path.join(bundle, "ocr_models"))
    dirs.append(os.path.join(_program_dir(), "vendor", "ocr_models"))
    out: List[str] = []
    for d in dirs:
        if d and d not in out:
            out.append(d)
    return out


def find_file(f: ModelFile) -> str:
    """Path of an installed model file ('' when missing). A file of the
    wrong size (interrupted copy) does not count."""
    for d in search_dirs():
        p = os.path.join(d, f.name)
        if os.path.isfile(p) and (not f.size or os.path.getsize(p) == f.size):
            return p
    return ""


@functools.lru_cache(maxsize=None)
def _has_module(name: str) -> bool:
    """Installed? (cheap: the module is looked for, not imported; cached,
    since nothing gets installed while the program runs)"""
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def builtin_available() -> bool:
    """The built-in model is the one inside the rapidocr package."""
    return _has_module("rapidocr") and _has_module("onnxruntime")


def is_installed(pack: OcrPack) -> bool:
    if pack.builtin:
        return builtin_available()
    return all(find_file(f) for f in pack.files)


def installed_ids() -> List[str]:
    return [p.id for p in PACKS if is_installed(p)]


def removable(pack: OcrPack) -> bool:
    """Only downloaded copies (in the user folder) can be removed."""
    if pack.builtin:
        return False
    base = os.path.normcase(os.path.abspath(user_models_dir()))
    for f in pack.files:
        p = find_file(f)
        if p and os.path.normcase(os.path.dirname(os.path.abspath(p))) == base:
            return True
    return False


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    """The system certificates (company proxies with their own root
    certificate work) plus certifi's list when it is present (frozen Linux
    builds, whose OpenSSL may not know where the system list is)."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:                                      # pragma: no cover
        pass
    return ctx


def _user_agent() -> str:
    try:
        from .. import APP_VERSION
    except Exception:                                      # pragma: no cover
        APP_VERSION = "?"
    return f"ConvertCAD/{APP_VERSION}"


def _fetch(url: str, target: str, f: ModelFile, done_before: int,
           total: int, progress: Optional[ProgressFn],
           should_cancel: Optional[Callable[[], bool]]) -> None:
    """Download one URL into `target` (checked), or raise."""
    part = target + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    digest = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                    context=_ssl_context()) as resp, \
                open(part, "wb") as out:
            if not total:
                total = done_before + int(resp.headers.get("Content-Length")
                                          or 0)
            while True:
                if should_cancel and should_cancel():
                    raise DownloadCancelled()
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                got += len(block)
                if progress:
                    progress(done_before + got, total)
        if digest.hexdigest() != f.sha256:
            raise DownloadError(f"{f.name}: the file received is damaged "
                                f"(checksum mismatch)")
        os.replace(part, target)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:                                # pragma: no cover
                pass


def download_pack(pack_id: str, progress: Optional[ProgressFn] = None,
                  should_cancel: Optional[Callable[[], bool]] = None,
                  dest: Optional[str] = None,
                  urls: Optional[Dict[str, List[str]]] = None) -> str:
    """Download every file of a pack into `dest` (default: the user models
    folder). Returns the folder. Raises DownloadError (with a readable
    message) or DownloadCancelled. Files already present are kept."""
    pack = BY_ID.get(pack_id)
    if pack is None:
        raise DownloadError(f"unknown OCR model '{pack_id}'")
    if pack.builtin:
        return ""
    dest = dest or user_models_dir()
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"cannot create {dest}: {exc}") from None
    urls = urls or pack.urls
    total = pack.size
    done = 0
    for f in pack.files:
        target = os.path.join(dest, f.name)
        if os.path.isfile(target) and _sha256(target) == f.sha256:
            done += os.path.getsize(target)
            continue
        errors = []
        for url in urls.get(f.name, []):
            try:
                _fetch(url, target, f, done, total, progress, should_cancel)
                break
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                errors.append(str(exc))
            except Exception as exc:                       # network, HTTP…
                errors.append(f"{_host(url)}: {exc}")
        else:
            raise DownloadError("; ".join(errors) or f"no address for "
                                                     f"{f.name}")
        done += os.path.getsize(target)
    return dest


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or url


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Offline installation and removal
# ---------------------------------------------------------------------------
_BY_SHA = {f.sha256: f for p in PACKS for f in p.files}


def install_files(paths: List[str], dest: Optional[str] = None) -> List[str]:
    """Copy model files downloaded on another computer into the models
    folder. Each file is recognised by its SHA-256 (any file name). Returns
    the ids of the packs that are complete afterwards; raises DownloadError
    when a file is not a ConvertCAD model."""
    dest = dest or user_models_dir()
    os.makedirs(dest, exist_ok=True)
    unknown, copied = [], set()
    for path in paths:
        f = _BY_SHA.get(_sha256(path))
        if f is None:
            unknown.append(os.path.basename(path))
            continue
        target = os.path.join(dest, f.name)
        if os.path.abspath(path) != os.path.abspath(target):
            shutil.copyfile(path, target + ".part")
            os.replace(target + ".part", target)
        copied.add(f.name)
    if unknown:
        raise DownloadError("not a ConvertCAD OCR model: " + ", ".join(unknown))
    return [p.id for p in PACKS if not p.builtin and is_installed(p)
            and any(f.name in copied for f in p.files)]


def remove_pack(pack_id: str) -> int:
    """Delete the downloaded files of a pack (user folder only). Returns
    the number of files removed."""
    pack = BY_ID[pack_id]
    base = user_models_dir()
    shared = {f.name for p in PACKS if p.id != pack_id and is_installed(p)
              for f in p.files}
    n = 0
    for f in pack.files:
        p = os.path.join(base, f.name)
        if f.name in shared or not os.path.isfile(p):
            continue
        os.remove(p)
        n += 1
    return n


def human_size(n: int) -> str:
    if n <= 0:
        return "?"
    if n < 1024 * 1024:
        return f"{max(n // 1024, 1)} KB"
    return f"{n / (1024 * 1024):.0f} MB"
