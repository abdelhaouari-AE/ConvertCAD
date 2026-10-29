"""
paths.py — file-name helpers shared by the engine, the batch dialog and the
command line. Standard library only (cheap to import at start-up).
"""

import os
from typing import List


def find_pdfs(folder: str, recursive: bool = False) -> List[str]:
    """PDF files of a folder (case-insensitive, no duplicates on Windows)."""
    found = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            found += [os.path.join(root, f) for f in files
                      if f.lower().endswith(".pdf")]
    else:
        try:
            found = [os.path.join(folder, f) for f in os.listdir(folder)
                     if f.lower().endswith(".pdf")
                     and os.path.isfile(os.path.join(folder, f))]
        except OSError:
            return []
    return sorted(set(os.path.normpath(p) for p in found), key=str.lower)


def output_paths(dxf_path: str, pages: List[int], page_mode: str
                 ) -> List[str]:
    """DXF file name(s) produced for a conversion."""
    if page_mode == "split" and len(pages) > 1:
        stem, ext = os.path.splitext(dxf_path)
        return [f"{stem}_p{p}{ext or '.dxf'}" for p in pages]
    return [dxf_path]


def with_extension(path: str, ext: str) -> str:
    """'plan.dxf' + '.dwg' -> 'plan.dwg' (any previous extension replaced)."""
    return os.path.splitext(path)[0] + ext
