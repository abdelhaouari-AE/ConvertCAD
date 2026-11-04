"""
check_lock.py — check that the installed libraries are exactly the versions
of requirements-lock.txt (run by the build and tests workflows after
"pip install -r requirements-dev.txt -c requirements-lock.txt").

    python scripts/check_lock.py

Fails when a library is installed in another version, or is not in the lock
at all (a new dependency was added without updating the lock: see CLAUDE.md,
"Dependencies").
"""

import os
import re
import sys
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "requirements-lock.txt")
# tools of the Python installation itself, not part of ConvertCAD
IGNORED = {"pip", "wheel", "uv", "pip-audit"}


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


def main() -> int:
    lock = locked()
    problems = []
    for dist in metadata.distributions():
        name = norm(dist.metadata["Name"] or "")
        if not name or name in IGNORED:
            continue
        if name not in lock:
            problems.append(f"{name} {dist.version}: not in requirements-lock.txt")
        elif dist.version != lock[name]:
            problems.append(f"{name}: installed {dist.version}, locked {lock[name]}")
    if problems:
        print("The installed libraries do not match requirements-lock.txt:")
        for p in sorted(set(problems)):
            print("  " + p)
        return 1
    print(f"OK: the installed libraries match requirements-lock.txt "
          f"({len(lock)} locked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
