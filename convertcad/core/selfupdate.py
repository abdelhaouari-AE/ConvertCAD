"""
selfupdate.py — update ConvertCAD by downloading only the files that changed.

How it works
------------
1. Every build writes the list of its files with their size and SHA-256
   checksum: _internal/update-manifest.json (scripts/make_manifest.py).
2. The portable zip of each release on GitHub contains every file and that
   list. GitHub serves PARTS of a file ("HTTP range requests"), so the program
   reads only the zip's table of contents and the new list (a few kB),
   compares the list with the files on the computer, and downloads only the
   files that are different. Each file is checked against its SHA-256.
3. The files are prepared in <program folder>/_update/<version>/files/ and
   put in place when ConvertCAD closes: a short "applier" process (the same
   program started with --apply-update) waits until ConvertCAD has closed,
   swaps the files and, if asked, starts the new version.
   On Windows a program file in use cannot be overwritten but it CAN be
   renamed: each old file becomes "<name>.cc-old" and the new file takes its
   name; the new version deletes the .cc-old files at its next start.
   If anything fails, every file is put back as it was: never half-updated.

Per-file updates need write access to the program folder: Windows portable
folder, or the normal Windows installation (for the current user). In the
other cases (installation for all users in Program Files, AppImage, .deb,
running from the source code) the program offers the full download.

Privacy: nothing about the user or the drawings is sent. The requests only
download public files of the GitHub release ("User-Agent: ConvertCAD/<v>").

This module never imports Qt: the interface (ui/update_bar.py), the
command line (cli.py: --check-update, --update) and the applier use it.
"""

import hashlib
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

MANIFEST = "update-manifest.json"         # the list of files (in _internal)
CONTENTS = "_internal"                    # PyInstaller's folder of files
MANIFEST_REL = f"{CONTENTS}/{MANIFEST}"
UPDATE_DIR = "_update"                    # work folder in the program folder
PENDING = "pending.json"                  # an update is ready to be applied
RESULT = "last-result.json"               # what the last applier did
OLD_SUFFIX = ".cc-old"                    # replaced files, deleted later
PORTABLE_MARKER = "ConvertCAD.portable"   # (config.py) portable settings
# installer/ConvertCAD.iss AppId: the Windows "Apps" entry to keep up to date
INNO_APP_ID = "{6E0B5D1A-3C7F-4B2E-9A64-C0F2D8A1B7E3}"
TIMEOUT_S = 30
CHUNK = 256 * 1024

# Test hook (used by scripts/update_selftest.py in the build workflow): file
# paths, separated by commas, downloaded again even when they are identical
# (to check that files in use can be replaced on Windows).
FORCE_ENV = "CONVERTCAD_UPDATE_FORCE"

ProgressFn = Callable[[int, int], None]          # (done bytes, total bytes)
CancelFn = Callable[[], bool]


class UpdateError(Exception):
    """The update could not be prepared or applied (message for the user)."""


class UpdateCancelled(UpdateError):
    pass


# ---------------------------------------------------------------------------
# Where the program is, what kind of installation it is
# ---------------------------------------------------------------------------
def program_dir() -> str:
    """Folder of ConvertCAD.exe (frozen program), else ''."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return ""


def platform_tag() -> str:
    if sys.platform == "win32":
        return "win64"
    if sys.platform.startswith("linux"):
        return "linux-x86_64"
    return sys.platform


def install_kind(app_dir: str = "") -> str:
    """source | win-portable | win-installed | appimage | deb | linux-portable"""
    if not getattr(sys, "frozen", False) and not app_dir:
        return "source"
    app = app_dir or program_dir()
    if sys.platform == "win32":
        # the installer leaves its uninstaller (unins000.exe) in the folder;
        # a folder unpacked from the portable zip has none
        try:
            names = os.listdir(app)
        except OSError:
            names = []
        if any(n.lower().startswith("unins") and n.lower().endswith(".exe")
               for n in names):
            return "win-installed"
        return "win-portable"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if app.startswith(("/opt/", "/usr/")):
        return "deb"
    return "linux-portable"


# The release file to download for a FULL update, per kind of installation
FULL_DOWNLOAD = {
    "win-installed": "-win64-setup.exe",
    "win-portable": "-win64-portable.zip",
    "appimage": ".AppImage",
    "deb": "_amd64.deb",
    "linux-portable": "-linux-x86_64.tar.gz",
}
# Installations that can be updated file by file (write access to the
# program folder), and the release file the files are read from. A Linux
# portable folder can be updated from a zip given on the command line
# (ConvertCAD-cli --update --update-from <zip>); the Linux release archive is
# a .tar.gz, which cannot be read in parts, so the program offers the full
# download there.
PATCH_KINDS = ("win-installed", "win-portable", "linux-portable")
PATCH_SOURCE = {"win-installed": "-win64-portable.zip",
                "win-portable": "-win64-portable.zip"}


def can_update_files(app_dir: str = "") -> Tuple[bool, str]:
    """(True, '') when this installation can be updated file by file,
    else (False, reason in English, for the log)."""
    kind = install_kind(app_dir)
    if kind not in PATCH_KINDS:
        return False, f"per-file updates are not available for '{kind}'"
    app = app_dir or program_dir()
    if read_manifest(app) is None:
        return False, "this version has no list of files"
    try:                                  # write access to the program folder?
        work = os.path.join(app, UPDATE_DIR)
        os.makedirs(work, exist_ok=True)
        probe = os.path.join(work, f".write-test-{os.getpid()}")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError:
        return False, "no write access to the program folder"
    return True, ""


# ---------------------------------------------------------------------------
# The list of files (manifest)
# ---------------------------------------------------------------------------
def _skipped(rel: str) -> bool:
    """Files never listed nor touched by an update: the update work folder,
    the portable settings, replaced files, the list itself and the Windows
    uninstaller (unins000.exe / .dat, written by the installer)."""
    parts = rel.split("/")
    top = parts[0]
    return (top in (UPDATE_DIR, "settings", PORTABLE_MARKER)
            or rel.endswith(OLD_SUFFIX) or rel == MANIFEST_REL
            or (len(parts) == 1 and top.lower().startswith("unins")))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(folder: str, version: str, platform: str = "") -> dict:
    files: Dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if _skipped(rel) or os.path.islink(full):
                continue
            st = os.stat(full)
            entry = {"size": st.st_size, "sha256": sha256_file(full)}
            if os.name != "nt" and st.st_mode & stat.S_IXUSR:
                entry["exec"] = True
            files[rel] = entry
    return {"format": 1, "app": "ConvertCAD", "version": version,
            "platform": platform or platform_tag(), "files": files}


def write_manifest(folder: str, version: str, platform: str = "") -> str:
    data = build_manifest(folder, version, platform)
    path = os.path.join(folder, CONTENTS, MANIFEST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    return path


def read_manifest(app_dir: str) -> Optional[dict]:
    try:
        with open(os.path.join(app_dir, CONTENTS, MANIFEST), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data.get("files"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Reading parts of the release zip (HTTP range requests, or a local file)
# ---------------------------------------------------------------------------
class _Source:
    """A zip file read by parts: a local path or an http(s) address."""

    def __init__(self, where: str):
        self.where = where
        self.is_url = where.startswith(("http://", "https://"))
        if self.is_url:
            self.size = self._remote_size()
        else:
            self.size = os.path.getsize(where)

    # -- http ------------------------------------------------------------
    def _request(self, start: int, end: int):
        from .ocr_store import _ssl_context, _user_agent
        req = urllib.request.Request(self.where, headers={
            "User-Agent": _user_agent(), "Accept-Encoding": "identity",
            "Range": f"bytes={start}-{end}"})
        ctx = _ssl_context() if self.where.startswith("https") else None
        return urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx)

    def _open_range(self, start: int, end: int):
        """Response for bytes start..end (included), with 3 tries."""
        last = None
        for attempt in range(3):
            try:
                resp = self._request(start, end)
                if resp.status != 206:     # the whole file would come: refuse
                    resp.close()
                    raise UpdateError("the server cannot send parts of the "
                                      "release file")
                return resp
            except UpdateError:
                raise
            except (urllib.error.URLError, OSError) as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        reason = getattr(last, "reason", last)
        raise UpdateError(f"GitHub could not be reached ({reason})")

    def _remote_size(self) -> int:
        # GitHub's file storage refuses HEAD requests: ask for the first
        # byte and read the total size in "Content-Range: bytes 0-0/<size>"
        with self._open_range(0, 0) as resp:
            total = (resp.headers.get("Content-Range") or "").rpartition("/")[2]
        if not total.isdigit():
            raise UpdateError("the size of the release file is unknown")
        return int(total)

    # -- both ------------------------------------------------------------
    def read(self, start: int, length: int) -> bytes:
        if length <= 0:
            return b""
        end = min(self.size, start + length) - 1
        if not self.is_url:
            with open(self.where, "rb") as fh:
                fh.seek(start)
                return fh.read(end - start + 1)
        with self._open_range(start, end) as resp:
            return resp.read()

    def stream(self, start: int, length: int, cancelled: Optional[CancelFn]):
        """Yield the bytes start .. start+length-1 in chunks."""
        if not self.is_url:
            with open(self.where, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    if cancelled and cancelled():
                        raise UpdateCancelled("cancelled")
                    block = fh.read(min(CHUNK, left))
                    if not block:
                        break
                    left -= len(block)
                    yield block
            return
        with self._open_range(start, start + length - 1) as resp:
            while True:
                if cancelled and cancelled():
                    raise UpdateCancelled("cancelled")
                block = resp.read(CHUNK)
                if not block:
                    break
                yield block


class _SeekableSource(io.RawIOBase):
    """File-like view of a _Source, for the zipfile module (it reads only the
    end of the file: the zip's table of contents). Blocks of 64 kB are kept
    so that the table of contents costs one or two requests."""
    BLOCK = 64 * 1024

    def __init__(self, src: _Source):
        super().__init__()
        self.src, self.pos, self.blocks = src, 0, {}

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        base = {0: 0, 1: self.pos, 2: self.src.size}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def _block(self, i):
        if i not in self.blocks:
            self.blocks[i] = self.src.read(i * self.BLOCK, self.BLOCK)
        return self.blocks[i]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.src.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.src.size:
            i, off = divmod(self.pos, self.BLOCK)
            chunk = self._block(i)[off:off + n]
            if not chunk:
                break
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


@dataclass
class Member:
    """One file inside the release zip."""
    name: str
    offset: int            # where its local header starts in the zip
    csize: int             # compressed size (what is downloaded)
    size: int
    crc: int
    method: int            # 0 stored, 8 deflate


def _zip_members(src: _Source) -> Dict[str, Member]:
    with zipfile.ZipFile(_SeekableSource(src)) as zf:
        return {i.filename: Member(i.filename, i.header_offset, i.compress_size,
                                   i.file_size, i.CRC, i.compress_type)
                for i in zf.infolist() if not i.is_dir()}


def _member_data_start(src: _Source, m: Member) -> int:
    """Offset of the compressed data: after the 30-byte local header, the
    file name and the local "extra" field (whose length can differ from the
    one in the table of contents)."""
    head = src.read(m.offset, 30)
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        raise UpdateError(f"damaged release file ({m.name})")
    name_len, extra_len = struct.unpack("<HH", head[26:30])
    return m.offset + 30 + name_len + extra_len


def _read_member(src: _Source, m: Member, out, cancelled=None,
                 progress=None) -> str:
    """Write the uncompressed file to `out` (binary file object), check its
    CRC-32 and size; return its SHA-256."""
    if m.method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise UpdateError(f"unsupported compression in the release ({m.name})")
    start = _member_data_start(src, m)
    inflate = zlib.decompressobj(-15) if m.method == zipfile.ZIP_DEFLATED else None
    sha, crc, size = hashlib.sha256(), 0, 0
    for block in src.stream(start, m.csize, cancelled):
        data = inflate.decompress(block) if inflate else block
        out.write(data)
        sha.update(data)
        crc = zlib.crc32(data, crc)
        size += len(data)
        if progress:
            progress(len(block))
    if inflate:
        tail = inflate.flush()
        out.write(tail)
        sha.update(tail)
        crc = zlib.crc32(tail, crc)
        size += len(tail)
    if size != m.size or (crc & 0xFFFFFFFF) != m.crc:
        raise UpdateError(f"the downloaded file is damaged ({m.name})")
    return sha.hexdigest()


# ---------------------------------------------------------------------------
# Prepare: what to download
# ---------------------------------------------------------------------------
@dataclass
class UpdatePlan:
    version: str                    # the new version
    source: str                     # release zip: address or path
    root: str                       # folder prefix inside the zip
    manifest: dict                  # the new version's list of files
    manifest_bytes: bytes
    files: List[Tuple[str, Member]] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    full_bytes: int = 0             # size of the whole release zip

    @property
    def download_bytes(self) -> int:
        return sum(m.csize for _, m in self.files)


def _same_file(path: str, meta: dict) -> bool:
    try:
        if os.path.getsize(path) != meta.get("size"):
            return False
        return sha256_file(path) == meta.get("sha256")
    except OSError:
        return False


def prepare(source: str, app_dir: str, cancelled: Optional[CancelFn] = None
            ) -> UpdatePlan:
    """Read the new version's list of files from the release zip and compare
    it with the files of this installation."""
    src = _Source(source)
    members = _zip_members(src)
    found = [n for n in members if n == MANIFEST_REL
             or n.endswith("/" + MANIFEST_REL)]
    if not found:
        raise UpdateError("this release cannot be installed file by file")
    name = min(found, key=len)
    root = name[:-len(MANIFEST_REL)]
    buf = io.BytesIO()
    _read_member(src, members[name], buf, cancelled)
    manifest_bytes = buf.getvalue()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        new_files = manifest["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateError("the list of files of the release is damaged") from exc
    if manifest.get("platform") not in (None, platform_tag()):
        raise UpdateError("this release file is for another system")
    force = {p.strip() for p in os.environ.get(FORCE_ENV, "").split(",")
             if p.strip()}
    plan = UpdatePlan(version=str(manifest.get("version") or "?"),
                      source=source, root=root, manifest=manifest,
                      manifest_bytes=manifest_bytes, full_bytes=src.size)
    for rel in sorted(new_files):
        if cancelled and cancelled():
            raise UpdateCancelled("cancelled")
        if _skipped(rel):
            continue
        if rel not in force and _same_file(os.path.join(app_dir, rel),
                                           new_files[rel]):
            continue
        member = members.get(root + rel)
        if member is None:
            raise UpdateError(f"the release file lacks {rel}")
        plan.files.append((rel, member))
    old = (read_manifest(app_dir) or {}).get("files", {})
    plan.removed = sorted(rel for rel in old if rel not in new_files
                          and not _skipped(rel)
                          and os.path.lexists(os.path.join(app_dir, rel)))
    return plan


def download(plan: UpdatePlan, app_dir: str,
             progress: Optional[ProgressFn] = None,
             cancelled: Optional[CancelFn] = None) -> str:
    """Download the changed files into _update/<version>/files, check each
    one, then write _update/pending.json (the update is ready)."""
    work = os.path.join(app_dir, UPDATE_DIR)
    stage = os.path.join(work, plan.version)
    files_dir = os.path.join(stage, "files")
    discard_pending(app_dir)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(files_dir, exist_ok=True)
    need = plan.download_bytes + sum(m.size for _, m in plan.files)
    try:
        if shutil.disk_usage(work).free < need + 50 * 2 ** 20:
            raise UpdateError("not enough free disk space for the update")
    except OSError:
        pass
    total, done = plan.download_bytes, 0

    def step(n):
        nonlocal done
        done += n
        if progress:
            progress(done, total)

    src = _Source(plan.source)
    new_files = plan.manifest["files"]
    for rel, member in plan.files:
        dest = os.path.join(files_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as fh:
            digest = _read_member(src, member, fh, cancelled, step)
        if digest != new_files[rel]["sha256"]:
            raise UpdateError(f"the downloaded file does not match ({rel})")
        os.replace(dest + ".part", dest)
        if new_files[rel].get("exec") and os.name != "nt":
            os.chmod(dest, os.stat(dest).st_mode | 0o111)
    # the new list of files goes in place with the files
    dest = os.path.join(files_dir, *MANIFEST_REL.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(plan.manifest_bytes)
    from .. import APP_VERSION
    pending = {"format": 1, "version": plan.version, "from_version": APP_VERSION,
               "files": [rel for rel, _ in plan.files] + [MANIFEST_REL],
               "removed": plan.removed, "downloaded": plan.download_bytes,
               "created": time.time()}
    _write_json(os.path.join(work, PENDING), pending)   # last: "ready"
    if progress:
        progress(total, total)
    return stage


def read_pending(app_dir: str) -> Optional[dict]:
    """The update waiting to be applied, if its files are all there."""
    try:
        with open(os.path.join(app_dir, UPDATE_DIR, PENDING), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
        files_dir = os.path.join(app_dir, UPDATE_DIR, str(data["version"]),
                                 "files")
        for rel in data["files"]:
            if not os.path.isfile(os.path.join(files_dir, *rel.split("/"))):
                return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def discard_pending(app_dir: str) -> None:
    data = read_pending(app_dir)
    try:
        os.remove(os.path.join(app_dir, UPDATE_DIR, PENDING))
    except OSError:
        pass
    if data:
        shutil.rmtree(os.path.join(app_dir, UPDATE_DIR, str(data["version"])),
                      ignore_errors=True)


# ---------------------------------------------------------------------------
# Apply (in the applier process, ConvertCAD being closed)
# ---------------------------------------------------------------------------
def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def _rename(a: str, b: str, tries: int = 25) -> None:
    """os.replace with patience: an antivirus may hold a new file a moment."""
    for i in range(tries):
        try:
            os.replace(a, b)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.2)


def _old_name(path: str) -> str:
    cand, n = path + OLD_SUFFIX, 1
    while os.path.lexists(cand):             # an older one not deleted yet
        cand, n = f"{path}.{n}{OLD_SUFFIX}", n + 1
    return cand


def apply_pending(app_dir: str, log: Callable[[str], None] = lambda s: None
                  ) -> Tuple[bool, str, str]:
    """Swap the prepared files in. (ok, version, message). On any error,
    every file already swapped is put back."""
    data = read_pending(app_dir)
    if not data:
        return False, "", "no update is ready"
    version = str(data["version"])
    work = os.path.join(app_dir, UPDATE_DIR)
    files_dir = os.path.join(work, version, "files")
    journal: List[Tuple[str, str]] = []           # (from, to) renames done
    try:
        for rel in data["files"]:
            src = os.path.join(files_dir, *rel.split("/"))
            dst = os.path.join(app_dir, *rel.split("/"))
            if os.path.lexists(dst):
                old = _old_name(dst)
                _rename(dst, old)
                journal.append((dst, old))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _rename(src, dst)
            journal.append((src, dst))
        for rel in data.get("removed", []):
            dst = os.path.join(app_dir, *rel.split("/"))
            if os.path.lexists(dst):
                old = _old_name(dst)
                _rename(dst, old)
                journal.append((dst, old))
    except Exception as exc:                          # put everything back
        log(f"update to {version} failed: {exc!r}; restoring the files")
        for a, b in reversed(journal):
            try:
                _rename(b, a)
            except Exception as exc2:                 # pragma: no cover
                log(f"  could not restore {a}: {exc2!r}")
        _write_json(os.path.join(work, RESULT), {
            "ok": False, "version": version, "message": str(exc),
            "time": time.time()})
        try:
            os.replace(os.path.join(work, PENDING),
                       os.path.join(work, "failed.json"))
        except OSError:
            pass
        return False, version, str(exc)
    os.remove(os.path.join(work, PENDING))
    shutil.rmtree(os.path.join(work, version), ignore_errors=True)
    _write_json(os.path.join(work, RESULT), {
        "ok": True, "version": version, "from_version": data.get("from_version"),
        "files": len(data["files"]), "downloaded": data.get("downloaded", 0),
        "time": time.time()})
    _update_windows_entry(app_dir, version, log)
    log(f"updated to {version}: {len(data['files'])} file(s) replaced, "
        f"{len(data.get('removed', []))} removed")
    return True, version, ""


def take_result(app_dir: str) -> Optional[dict]:
    """What the last update did (read once, for a message at start-up)."""
    path = os.path.join(app_dir, UPDATE_DIR, RESULT)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        os.remove(path)
        return data
    except (OSError, ValueError):
        return None


def cleanup_old(app_dir: str) -> int:
    """Delete the replaced files (*.cc-old) and the folders left empty.
    Files still in use stay for next time. Returns the number deleted."""
    if not app_dir or not os.path.isdir(app_dir):
        return 0
    count = 0
    for dirpath, _dirnames, filenames in os.walk(app_dir, topdown=False):
        rel_dir = os.path.relpath(dirpath, app_dir).replace(os.sep, "/")
        if rel_dir.split("/")[0] in (UPDATE_DIR, "settings"):
            continue
        for name in filenames:
            if name.endswith(OLD_SUFFIX):
                try:
                    os.remove(os.path.join(dirpath, name))
                    count += 1
                except OSError:
                    pass
        if rel_dir.startswith(CONTENTS + "/") and not os.listdir(dirpath):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    return count


def _update_windows_entry(app_dir: str, version: str, log) -> None:
    """Version shown in Windows Settings > Apps (installed for the current
    user: the installer's entry is in HKEY_CURRENT_USER)."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        key_path = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                    f"\\{INNO_APP_ID}_is1")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            loc = winreg.QueryValueEx(key, "InstallLocation")[0]
            if (os.path.normcase(os.path.abspath(str(loc).rstrip("\\/")))
                    != os.path.normcase(os.path.abspath(app_dir))):
                return
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ,
                              f"ConvertCAD {version}")
            nums = [int(x) for x in version.split(".")[:2] if x.isdigit()]
            for name, value in zip(("MajorVersion", "MinorVersion"), nums):
                try:
                    winreg.QueryValueEx(key, name)
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                except OSError:
                    pass
    except OSError as exc:
        log(f"Windows Apps entry not updated: {exc!r}")


# ---------------------------------------------------------------------------
# The applier process: ConvertCAD(.exe) --apply-update ...
# ---------------------------------------------------------------------------
def wait_for_exit(pid: int, timeout_s: float = 120.0) -> bool:
    """Wait until process `pid` has ended. False on time-out."""
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:                       # already ended
            return True
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:              # pragma: no cover
            pass
        time.sleep(0.2)
    return False


def _spawn(cmd: List[str], cwd: str) -> None:
    """Start a program that outlives this one, without a console window."""
    kwargs = dict(cwd=cwd, close_fds=True, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32":
        detached, new_group, breakaway = 0x8, 0x200, 0x01000000
        try:
            subprocess.Popen(cmd, creationflags=detached | new_group | breakaway,
                             **kwargs)
            return
        except OSError:                      # job object without breakaway
            subprocess.Popen(cmd, creationflags=detached | new_group, **kwargs)
            return
    subprocess.Popen(cmd, start_new_session=True, **kwargs)


def start_applier(relaunch: bool, args: Optional[List[str]] = None) -> None:
    """Called by ConvertCAD just before it closes: start the applier, which
    waits for this process to end, then swaps the files."""
    exe = sys.executable
    cmd = [exe, "--apply-update", "--wait-pid", str(os.getpid())]
    if not relaunch:
        cmd.append("--no-relaunch")
    if args:
        cmd += ["--"] + list(args)
    _spawn(cmd, os.path.dirname(exe))


def _log_to_file(text: str) -> None:
    try:
        from ..config import settings_dir
        folder = settings_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "update.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + text + "\n")
    except OSError:                          # pragma: no cover
        pass


def run_applier(argv: List[str]) -> int:
    """Entry of 'ConvertCAD --apply-update [--wait-pid N] [--no-relaunch]
    [-- arguments for the relaunched program]'. Returns the exit code."""
    args = list(argv)
    rest: List[str] = []
    if "--" in args:
        i = args.index("--")
        args, rest = args[:i], args[i + 1:]
    pid = 0
    if "--wait-pid" in args:
        try:
            pid = int(args[args.index("--wait-pid") + 1])
        except (IndexError, ValueError):
            pid = 0
    relaunch = "--no-relaunch" not in args
    app = program_dir() or os.getcwd()
    _log_to_file(f"applier started (pid {os.getpid()}), waiting for {pid}")
    if not wait_for_exit(pid):
        _log_to_file("ConvertCAD did not close: update not applied")
        ok = False
    else:
        time.sleep(0.3)                      # let Windows release the files
        ok, version, message = apply_pending(app, _log_to_file)
    if relaunch:
        _spawn([sys.executable, "--update-done" if ok else "--update-failed"]
               + rest, app)
    return 0 if ok else 1
