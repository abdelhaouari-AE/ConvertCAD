# Instructions for AI coding assistants

The rules of this repository are in **[CLAUDE.md](CLAUDE.md)** — read it
before changing anything. The most important one:

**Dependencies:** releases are built with the exact versions of
`requirements-lock.txt` (and the Python version pinned in
`.github/workflows/build.yml`). Change a version only when a newer one fixes
a security vulnerability (pip-audit / Dependabot) or brings a fix or a
feature ConvertCAD needs; update only that library, run the tests, note it
in `CHANGELOG.md`. Never add a library without adding it to the lock.
