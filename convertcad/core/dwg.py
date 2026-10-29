"""
dwg.py — native DWG output with the bundled GNU LibreDWG converter.

Why LibreDWG?
-------------
DWG is a closed format: the only programs that write it are AutoCAD, the
commercial ODA Drawings SDK, and the free GNU LibreDWG project. The free ODA
File Converter may NOT be redistributed with other software (ODA Community
User Agreement, section 3.1.1) and is limited to non-commercial use for
non-members, so it cannot ship inside ConvertCAD. LibreDWG is free software
(GPL-3.0-or-later, compatible with ConvertCAD's AGPL-3.0): its `dxf2dwg`
program travels inside the portable folder and the installer, and the user
installs nothing.

LibreDWG writes DWG in the AutoCAD 2000 format (AC1015). Every AutoCAD
release since 2000 and every current CAD program opens it.

How a DWG is made
-----------------
1. ConvertCAD writes the drawing as an AutoCAD 2000 DXF (Options.output_format
   "dwg" switches the writer to R2000: classic LEADER, ACI colours...).
2. prepare_dxf_for_dwg() adapts that DXF to what LibreDWG's reader expects:
     * objects that do not exist in AutoCAD 2000 are removed (MATERIAL,
       MLEADERSTYLE, VISUALSTYLE...), with their dictionary entries;
     * MTEXT rotation is written as a direction vector (code 11) instead of
       an angle (code 50, rejected by LibreDWG 0.13);
     * handles are renumbered so the model-space block record sits on the
       handle AutoCAD reserves for it (0x1F) and no handle collides with the
       objects LibreDWG creates itself (VX table 0xB...).
3. `dxf2dwg --as r2000` writes the DWG.
4. verify_dwg() reads the DWG back (`dwg2dxf`) and compares the number of
   drawing entities: a DWG is only reported as written when it is complete.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Objects introduced after AutoCAD 2000: never written into a DWG 2000.
_POST_R2000_OBJECTS = ("MATERIAL", "MLEADERSTYLE", "VISUALSTYLE",
                       "TABLESTYLE", "SCALE", "CELLSTYLEMAP", "SUN",
                       "DETAILVIEWSTYLE", "SECTIONVIEWSTYLE")
_POST_R2000_DICTS = ("ACAD_MATERIAL", "ACAD_MLEADERSTYLE", "ACAD_VISUALSTYLE",
                     "ACAD_TABLESTYLE", "ACAD_SCALELIST",
                     "ACAD_DETAILVIEWSTYLE", "ACAD_SECTIONVIEWSTYLE")

# DXF group codes whose value is a handle (hexadecimal)
_HANDLE_CODES = ({5, 105, 1005} | set(range(320, 370)) | set(range(390, 400))
                 | {480, 481})
MODEL_SPACE_HANDLE = 0x1F          # AutoCAD's handle of *Model_Space
HANDLE_SHIFT = 0x30                # moves ezdxf's handles clear of 0x01-0x2F
# AutoCAD's fixed handles of the table heads (control objects); LibreDWG
# expects this layout (with another one it lists linetypes twice).
_TABLE_HANDLES = {"BLOCK_RECORD": 0x1, "LAYER": 0x2, "STYLE": 0x3,
                  "LTYPE": 0x5, "VIEW": 0x6, "UCS": 0x7, "VPORT": 0x8,
                  "APPID": 0x9, "DIMSTYLE": 0xA}
TIMEOUT_S = 600


@dataclass
class DwgTools:
    """Where the LibreDWG programs are (empty strings when missing)."""
    dxf2dwg: str = ""
    dwg2dxf: str = ""
    lib_dir: str = ""              # Linux bundle: folder of libredwg.so
    version: str = ""

    @property
    def available(self) -> bool:
        return bool(self.dxf2dwg)


@dataclass
class DwgResult:
    ok: bool = False
    dwg_path: str = ""
    message: str = ""
    entities_dxf: int = 0          # drawing entities in the source DXF
    entities_dwg: int = -1         # ...read back from the DWG (-1 = unchecked)
    seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Finding the bundled converter
# ---------------------------------------------------------------------------
def _candidate_dirs() -> List[str]:
    exe_dir = os.path.dirname(getattr(sys, "executable", "") or "")
    project = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    bundle = getattr(sys, "_MEIPASS", "")
    platform_dir = "win64" if os.name == "nt" else "linux-x86_64"
    dirs = [os.path.join(exe_dir, "libredwg"),
            os.path.join(project, "libredwg"),
            os.path.join(project, "vendor", "libredwg", platform_dir)]
    if bundle:
        dirs.append(os.path.join(bundle, "libredwg"))
    env = os.environ.get("CONVERTCAD_LIBREDWG", "")
    if env:
        dirs.insert(0, env)
    return dirs


def _exe(name: str) -> str:
    return name + ".exe" if os.name == "nt" else name


_TOOLS_CACHE: Optional[DwgTools] = None


def find_tools(refresh: bool = False) -> DwgTools:
    """Locate dxf2dwg / dwg2dxf: bundled folder first, then the PATH."""
    global _TOOLS_CACHE
    if _TOOLS_CACHE is not None and not refresh:
        return _TOOLS_CACHE
    tools = DwgTools()
    for d in _candidate_dirs():
        for sub in ("", "bin"):
            folder = os.path.join(d, sub)
            exe = os.path.join(folder, _exe("dxf2dwg"))
            if os.path.isfile(exe):
                tools.dxf2dwg = exe
                back = os.path.join(folder, _exe("dwg2dxf"))
                tools.dwg2dxf = back if os.path.isfile(back) else ""
                lib = os.path.join(d, "lib")
                tools.lib_dir = lib if os.path.isdir(lib) else ""
                break
        if tools.dxf2dwg:
            break
    if not tools.dxf2dwg:
        tools.dxf2dwg = shutil.which("dxf2dwg") or ""
        tools.dwg2dxf = shutil.which("dwg2dxf") or ""
    for exe in (tools.dxf2dwg, tools.dwg2dxf):   # copied without its x bit?
        if exe and os.name != "nt" and not os.access(exe, os.X_OK):
            try:
                os.chmod(exe, 0o755)
            except OSError:                        # read-only (AppImage)
                pass
    if tools.dxf2dwg:
        try:
            out = _run([tools.dxf2dwg, "--version"], tools, timeout=20)
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout or "")
            tools.version = m.group(1) if m else ""
        except Exception:                                  # pragma: no cover
            pass
    _TOOLS_CACHE = tools
    return tools


def dwg_status() -> Dict[str, object]:
    """For the interface and the About box."""
    t = find_tools()
    return {"available": t.available, "path": t.dxf2dwg,
            "version": t.version, "verify": bool(t.dwg2dxf)}


def _run(cmd: List[str], tools: DwgTools, timeout: int = TIMEOUT_S,
         cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if tools.lib_dir:                         # Linux bundle: private .so files
        env["LD_LIBRARY_PATH"] = tools.lib_dir + os.pathsep + \
            env.get("LD_LIBRARY_PATH", "")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no console flash
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=cwd, env=env,
                          creationflags=flags)


# ---------------------------------------------------------------------------
# 1. Adapt the DXF to LibreDWG's reader
# ---------------------------------------------------------------------------
def _clean_with_ezdxf(src_dxf: str, dst_dxf: str) -> None:
    """Remove post-2000 objects and rewrite MTEXT rotations (ezdxf)."""
    import math

    import ezdxf
    doc = ezdxf.readfile(src_dxf)
    root = doc.rootdict
    # 1. unlink the post-2000 dictionaries from the root dictionary
    orphans = []
    for name in _POST_R2000_DICTS:
        sub = root.get(name)
        if sub is None:
            continue
        root.discard(name)
        if hasattr(sub, "dxftype"):
            orphans.append(sub)
    # 2. delete the post-2000 objects, then their (now empty) dictionaries
    for obj in list(doc.objects):
        if obj.is_alive and obj.dxftype() in _POST_R2000_OBJECTS:
            try:
                doc.objects.delete_entity(obj)
            except Exception:                      # pragma: no cover
                pass
    for sub in orphans:
        if sub.is_alive:
            try:
                sub.clear()
                doc.objects.delete_entity(sub)
            except Exception:                      # pragma: no cover
                pass
    layouts = [doc.modelspace()] + [b for b in doc.blocks]
    for space in layouts:
        for e in space.query("MTEXT"):
            if e.dxf.hasattr("rotation"):
                a = math.radians(e.dxf.rotation)
                e.dxf.discard("rotation")
                e.dxf.text_direction = (math.cos(a), math.sin(a), 0.0)
    doc.saveas(dst_dxf)


def _remap_handles(path: str) -> None:
    """Renumber every handle of a DXF file (text level, keeps references).

    *Model_Space -> 0x1F; table heads (handles below 0x0A) unchanged;
    everything else shifted by HANDLE_SHIFT."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    n = len(lines) - (len(lines) % 2)
    # find the *Model_Space BLOCK_RECORD and the table heads
    ms_handle = None
    tables: Dict[int, int] = {}            # old handle -> AutoCAD handle
    cur = ""
    table_name = ""
    rec_handle = None
    for i in range(0, n, 2):
        code, value = lines[i].strip(), lines[i + 1].strip()
        if code == "0":
            cur = value
            rec_handle = None
            table_name = ""
        elif cur == "TABLE" and code == "2":
            table_name = value.upper()
        elif cur == "TABLE" and code == "5" and table_name in _TABLE_HANDLES:
            tables[int(value, 16)] = _TABLE_HANDLES[table_name]
        elif cur == "BLOCK_RECORD" and code == "5":
            rec_handle = value
        elif cur == "BLOCK_RECORD" and code == "2" and \
                value.upper() == "*MODEL_SPACE" and rec_handle:
            ms_handle = int(rec_handle, 16)
    if ms_handle is None:
        raise ValueError("no *Model_Space block record in the DXF")

    def new_handle(h: int) -> int:
        if h == 0:
            return 0
        if h == ms_handle:
            return MODEL_SPACE_HANDLE
        if h in tables:
            return tables[h]
        return h + HANDLE_SHIFT

    highest = MODEL_SPACE_HANDLE
    seed_line = -1
    in_header = False
    prev_value = ""
    for i in range(0, n, 2):
        raw_code = lines[i].strip()
        if raw_code == "2" and lines[i + 1].strip() == "HEADER":
            in_header = True
        elif raw_code == "0" and lines[i + 1].strip() == "ENDSEC":
            in_header = False
        try:
            code = int(raw_code)
        except ValueError:
            continue
        if in_header and code == 9:
            prev_value = lines[i + 1].strip()
            continue
        if code not in _HANDLE_CODES:
            continue
        if in_header and prev_value == "$HANDSEED":
            seed_line = i + 1
            continue
        value = lines[i + 1].strip()
        try:
            h = int(value, 16)
        except ValueError:
            continue
        nh = new_handle(h)
        highest = max(highest, nh)
        lines[i + 1] = format(nh, "X")
    if seed_line >= 0:
        lines[seed_line] = format(highest + 1, "X")
    _fix_ltype_count(lines, n)
    lines = _complete_insert_scales(lines)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


_SCALE_CODES = ("41", "42", "43")


def _complete_insert_scales(lines: List[str]) -> List[str]:
    """Give every scaled INSERT its three scale factors (groups 41, 42, 43).

    ezdxf leaves out a factor equal to 1.0. LibreDWG 0.13.4 then takes the
    missing Y / Z factor from the Y / Z of the insertion point, so a
    mirrored copy (X = -1) came out stretched hundreds of times (fixed in
    the bundled build by patches/03; done here too for any LibreDWG)."""
    n = len(lines) - (len(lines) % 2)
    out: List[str] = []
    i = 0
    while i < n:
        out += lines[i:i + 2]
        if lines[i].strip() != "0" or lines[i + 1].strip() != "INSERT":
            i += 2
            continue
        j = i + 2                                   # end of this entity
        while j < n and lines[j].strip() != "0":
            j += 2
        pairs = [(lines[k], lines[k + 1]) for k in range(i + 2, j, 2)]
        codes = [c.strip() for c, _ in pairs]
        have = [c for c in _SCALE_CODES if c in codes]
        if have and len(have) < 3:
            value = {c: pairs[codes.index(c)][1].strip() for c in have}
            rest = [p for p in pairs if p[0].strip() not in _SCALE_CODES]
            point = [k for k, p in enumerate(rest)
                     if p[0].strip() in ("10", "20", "30")]
            at = point[-1] + 1 if point else len(rest)
            rest[at:at] = [(f"{c:>3}", value.get(c, "1.0"))
                           for c in _SCALE_CODES]
            pairs = rest
        for code, val in pairs:
            out += [code, val]
        i = j
    out += lines[n:]
    return out


def _fix_ltype_count(lines: List[str], n: int) -> None:
    """AutoCAD counts the LTYPE table WITHOUT ByBlock / ByLayer (group 70 of
    the TABLE header); with ezdxf's count LibreDWG lists every linetype
    twice in the DWG linetype table."""
    count_line = -1                   # line holding the TABLE's group 70
    in_table = False
    records = 0                       # LTYPE records except ByBlock/ByLayer
    for i in range(0, n, 2):
        code, value = lines[i].strip(), lines[i + 1].strip()
        if code == "0" and value == "TABLE":
            in_table = i + 3 < len(lines) and lines[i + 3].strip() == "LTYPE"
            continue
        if not in_table:
            continue
        if code == "0" and value == "ENDTAB":
            break
        if code == "70" and count_line < 0 and records == 0:
            count_line = i + 1        # first 70 = the table header's count
        elif code == "0" and value == "LTYPE":
            records += 1
        elif code == "2" and value.upper() in ("BYBLOCK", "BYLAYER"):
            records -= 1
    if count_line >= 0:
        lines[count_line] = str(max(records, 0))


def prepare_dxf_for_dwg(src_dxf: str, dst_dxf: str) -> None:
    """Write `dst_dxf`, a copy of `src_dxf` that LibreDWG converts cleanly."""
    _clean_with_ezdxf(src_dxf, dst_dxf)
    _remap_handles(dst_dxf)


# ---------------------------------------------------------------------------
# 2. Count entities (verification)
# ---------------------------------------------------------------------------
_ENTITY_SKIP = {"SEQEND", "VERTEX", "ATTRIB", "ENDBLK", "BLOCK",
                "ENDSEC", "SECTION", "EOF"}


def count_dxf_entities(path: str) -> int:
    """Number of drawing entities in the ENTITIES section (text scan: fast
    and independent from the program that wrote the file)."""
    count = 0
    section = ""
    expect_name = False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        code = None
        for k, line in enumerate(fh):
            if k % 2 == 0:
                code = line.strip()
                continue
            value = line.strip()
            if code != "0" and not (code == "2" and expect_name):
                continue
            if code == "2" and expect_name:
                section = value
                expect_name = False
                continue
            if value == "SECTION":
                expect_name = True
            elif value == "ENDSEC":
                section = ""
            elif section == "ENTITIES" and value not in _ENTITY_SKIP:
                count += 1
    return count


def insert_transforms(path: str) -> Counter:
    """Position, scale and rotation of every block reference (INSERT) of
    the ENTITIES section: a text scan, independent from the writer.
    Factors left out of the file count as 1, a missing rotation as 0."""
    found: Counter = Counter()
    section, cur, expect_name = "", None, False

    def close(rec):
        if rec is not None:
            found[tuple(round(rec.get(c, d), 4) for c, d in
                        (("10", 0.0), ("20", 0.0), ("41", 1.0),
                         ("42", 1.0), ("43", 1.0), ("50", 0.0)))] += 1

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        code = None
        for k, line in enumerate(fh):
            if k % 2 == 0:
                code = line.strip()
                continue
            value = line.strip()
            if code == "0":
                close(cur)
                cur = None
                if value == "SECTION":
                    expect_name = True
                elif value == "ENDSEC":
                    section = ""
                elif section == "ENTITIES" and value == "INSERT":
                    cur = {}
            elif code == "2" and expect_name:
                section, expect_name = value, False
            elif cur is not None and code in ("10", "20", "41", "42", "43",
                                              "50"):
                try:
                    cur[code] = float(value)
                except ValueError:
                    pass
    close(cur)
    return found


def _read_back(dwg_path: str, tools: DwgTools) -> Tuple[int, Counter]:
    """Read a DWG back with dwg2dxf: (entity count, INSERT transforms)."""
    with tempfile.TemporaryDirectory(prefix="convertcad_dwg_") as tmp:
        back = os.path.join(tmp, "check.dxf")
        res = _run([tools.dwg2dxf, "-y", "-o", back, dwg_path], tools)
        if res.returncode != 0 or not os.path.isfile(back):
            raise RuntimeError(_last_error(res) or "the DWG could not be "
                                                   "read back")
        return count_dxf_entities(back), insert_transforms(back)


def verify_dwg(dwg_path: str, tools: Optional[DwgTools] = None) -> int:
    """Read a DWG back with dwg2dxf; returns its entity count (-1 if the
    check cannot run)."""
    tools = tools or find_tools()
    if not tools.dwg2dxf:
        return -1
    return _read_back(dwg_path, tools)[0]


def _last_error(res: subprocess.CompletedProcess) -> str:
    text = (res.stderr or "") + "\n" + (res.stdout or "")
    errs = [ln.strip() for ln in text.splitlines()
            if "ERROR" in ln.upper() and ln.strip()]
    return errs[0] if errs else ""


def _is_dwg2000(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(6) == b"AC1015"
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 3. Main entry
# ---------------------------------------------------------------------------
def dxf_to_dwg(src_dxf: str, dwg_path: str, verify: bool = True,
               tools: Optional[DwgTools] = None) -> DwgResult:
    """Convert a ConvertCAD DXF to DWG (AutoCAD 2000). Never raises."""
    t0 = time.time()
    res = DwgResult(dwg_path=dwg_path)
    tools = tools or find_tools()
    if not tools.available:
        res.message = ("DWG output unavailable: the LibreDWG converter "
                       "(dxf2dwg) was not found next to ConvertCAD.")
        return res
    try:
        res.entities_dxf = count_dxf_entities(src_dxf)
        with tempfile.TemporaryDirectory(prefix="convertcad_dwg_") as tmp:
            work_dxf = os.path.join(tmp, "drawing.dxf")
            work_dwg = os.path.join(tmp, "drawing.dwg")
            prepare_dxf_for_dwg(src_dxf, work_dxf)
            run = _run([tools.dxf2dwg, "-y", "--as", "r2000", "-o", work_dwg,
                        work_dxf], tools)
            if run.returncode != 0 or not _is_dwg2000(work_dwg):
                res.message = ("LibreDWG could not write the DWG: "
                               + (_last_error(run) or
                                  f"exit code {run.returncode}"))
                return res
            if verify and tools.dwg2dxf:
                res.entities_dwg, inserts = _read_back(work_dwg, tools)
                if res.entities_dwg < res.entities_dxf:
                    res.message = (f"The DWG is incomplete: "
                                   f"{res.entities_dwg} of "
                                   f"{res.entities_dxf} entities read "
                                   f"back.")
                    return res
                moved = sum((insert_transforms(work_dxf) - inserts).values())
                if moved:
                    res.message = (f"The DWG is not faithful: {moved} block "
                                   f"reference(s) changed position, scale "
                                   f"or rotation.")
                    return res
            os.makedirs(os.path.dirname(os.path.abspath(dwg_path)),
                        exist_ok=True)
            shutil.copyfile(work_dwg, dwg_path)
        res.ok = True
        res.message = "DWG written (AutoCAD 2000 format)."
    except subprocess.TimeoutExpired:
        res.message = "DWG conversion took too long and was stopped."
    except Exception as exc:
        res.message = f"DWG conversion failed: {exc}"
    finally:
        res.seconds = time.time() - t0
    return res
