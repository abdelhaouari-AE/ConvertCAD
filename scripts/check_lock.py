"""
check_lock.py — check that the libraries ConvertCAD uses are installed in
exactly the versions of requirements-lock.txt (run by the build and tests
workflows after
    python -m pip install -r requirements-dev.txt -c requirements-lock.txt).

    python scripts/check_lock.py

It follows the dependency tree of requirements-dev.txt (requirements.txt
included): every library in that tree must be in the lock, at the locked
version. Other tools installed on the machine (pipx on GitHub's Windows
runners, for example) are not ConvertCAD's and are ignored.
Fails when a library of the tree is missing from the lock (a dependency was
added without updating the lock) or has another version (see CLAUDE.md,
"Dependencies").
"""

import os
import re
import sys
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "requirements-lock.txt")
NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)(\[([^\]]*)\])?")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked() -> dict:
    out = {}
    with open(LOCK, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line)
            if m:
                out[norm(m.group(1))] = m.group(2)
    return out


def top_level(path: str, seen=None) -> list:
    """(name, extras) of a requirements file, following -r includes."""
    seen = seen if seen is not None else set()
    path = os.path.abspath(path)
    if path in seen:
        return []
    seen.add(path)
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith(("-r ", "--requirement ")):
                inc = line.split(None, 1)[1].strip()
                out += top_level(os.path.join(os.path.dirname(path), inc), seen)
                continue
            if line.startswith("-"):
                continue
            m = NAME.match(line)
            if m:
                extras = [e.strip() for e in (m.group(3) or "").split(",")
                          if e.strip()]
                out.append((m.group(1), extras))
    return out


def _applies(marker_text: str, extras) -> bool:
    """Does a dependency marker apply here (this system, these extras)?"""
    if not marker_text:
        return True
    try:
        from packaging.markers import Marker
    except ImportError:                      # pragma: no cover
        return True                          # without packaging: check all
    marker = Marker(marker_text)
    return any(marker.evaluate({"extra": e}) for e in (list(extras) or [""]))


def tree(roots) -> dict:
    """Every installed library reached from the roots: {name: version}.
    Names required but not installed are reported with version None."""
    found, todo = {}, [(n, set(x)) for n, x in roots]
    done = set()
    while todo:
        name, extras = todo.pop()
        key = (norm(name), frozenset(extras))
        if key in done:
            continue
        done.add(key)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            found.setdefault(norm(name), None)
            continue
        found[norm(name)] = dist.version
        for req in dist.requires or []:
            text, _, marker = req.partition(";")
            if not _applies(marker.strip(), extras):
                continue
            m = NAME.match(text)
            if m:
                sub = {e.strip() for e in (m.group(3) or "").split(",")
                       if e.strip()}
                todo.append((m.group(1), sub))
    return found


def main() -> int:
    lock = locked()
    used = tree(top_level(os.path.join(ROOT, "requirements-dev.txt")))
    problems = []
    for name, version in sorted(used.items()):
        if version is None:
            problems.append(f"{name}: required but not installed")
        elif name not in lock:
            problems.append(f"{name} {version}: not in requirements-lock.txt")
        elif version != lock[name]:
            problems.append(f"{name}: installed {version}, locked {lock[name]}")
    if problems:
        print("The libraries of ConvertCAD do not match requirements-lock.txt:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"OK: the {len(used)} libraries of ConvertCAD match "
          f"requirements-lock.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
