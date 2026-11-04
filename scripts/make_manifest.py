"""
make_manifest.py — write the list of files of a build (for small updates).

    python scripts/make_manifest.py dist/ConvertCAD

Writes dist/ConvertCAD/_internal/update-manifest.json: every file of the
program folder with its size and SHA-256. Run it LAST, on the final folder
(after signing and after copying README, LICENSE...), just before making the
zip and the installer: the program compares this list with the files on the
user's computer to download only what changed (convertcad/core/selfupdate.py).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from convertcad import APP_VERSION  # noqa: E402
from convertcad.core.selfupdate import write_manifest  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        print(__doc__)
        return 2
    path = write_manifest(sys.argv[1], APP_VERSION)
    import json
    with open(path, encoding="utf-8") as fh:
        files = json.load(fh)["files"]
    total = sum(f["size"] for f in files.values())
    print(f"Written: {path} ({len(files)} files, {total / 2 ** 20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
