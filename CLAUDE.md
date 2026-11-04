# ConvertCAD — rules for working on this repository

Read by Claude Code (terminal, VS Code, web) at the start of every session.
Other AI assistants read AGENTS.md, which points here. People: same rules.

## The project in short

- Offline desktop converter PDF → DXF / DWG. Python 3.10+, PySide6 interface
  in `convertcad/ui/`, conversion engine in `convertcad/core/` (it never
  imports Qt), command line in `convertcad/cli.py`.
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -q` — lint:
  `python -m ruff check .` — both must pass before any commit.
- Interface texts: the English text is the key. Every string given to `tr()`
  needs its French translation (`_fr({...})` blocks in `convertcad/i18n.py`)
  and its Spanish, German and Arabic ones (`convertcad/locales/*.py`);
  `tests/test_i18n.py` fails otherwise.
- The version number lives only in `convertcad/__init__.py` (`APP_VERSION`).
  The `CHANGELOG.md` section of a version becomes its release notes.
- Full technical description: `docs/DEVELOPMENT.md`; build and release:
  `docs/PACKAGING.md`.

## Dependencies — MUST be followed

1. **Releases are built with exact versions.** `requirements-lock.txt` lists
   every library with its exact version (build tools included). Python itself
   is pinned in `.github/workflows/build.yml` (3.12.10 on Windows, 3.12.15 on
   Linux). `requirements.txt` keeps the allowed *ranges*, for running from the
   source code.
2. **Never** change a locked version without a reason below, never let a
   build take "the newest version", and never add a library without adding
   it to the lock: `scripts/check_lock.py` fails the build when the installed
   versions differ from the lock.
3. **Update a library (or Python) only when a newer version**
   - **fixes a security vulnerability** — the `tests` and weekly `security`
     workflows run `pip-audit` on the lock and fail when one is known;
     Dependabot opens security pull requests. Apply such updates promptly;
   - **or brings a fix or a feature ConvertCAD needs** — say which in
     `CHANGELOG.md`.
   Python 3.12 no longer gets Windows binaries: to get Python security fixes
   on Windows, move to a newer Python version (a deliberate update, tested).
4. **How to update one library:**
   `uv pip compile requirements-dev.txt --universal --python-version 3.12 --upgrade-package <name> -o requirements-lock.txt`
   (widen its range in `requirements.txt` if needed), run the tests and
   `python -m pip_audit -r requirements-lock.txt --no-deps --disable-pip`,
   add a "Libraries" line to `CHANGELOG.md`, release.
5. **Why:** an update downloads only the files that changed. A library left
   at the same version keeps the same files, so updates stay small (a few
   MB instead of 170 MB) and nothing changes behind our back.

## Small updates (per-file updater) — keep them working

- `convertcad/core/selfupdate.py` downloads only the changed files, read by
  parts from the release's portable zip. Do not break these conditions:
  - `ConvertCAD.spec`: our own code is collected as separate `.pyc` files
    (`OWN_CODE_AS_FILES`) and the program archives are separate files
    (`append_pkg=False`, `ConvertCAD.pkg`, `ConvertCAD-cli.pkg`);
  - builds run with `PYTHONHASHSEED=0` and `SOURCE_DATE_EPOCH` (identical
    files for identical code);
  - `scripts/make_manifest.py` runs LAST on the final program folder (after
    signing and copying the documents), before the zip and the installer;
    the portable zip must contain `ConvertCAD/_internal/update-manifest.json`;
  - the applier (`--apply-update`, in `main.py` and `convertcad_cli.py`)
    runs before any other import; on Windows it runs from a copy
    (`make_runner`: the CLI program, its `.pkg`, the top-level files of
    `_internal`, our `.pyc`), because a running program cannot rename its
    own files — keep the code it imports to the standard library;
  - `scripts/update_selftest.py` (build workflow, Windows and Linux) must
    pass.
- A release built without these breaks the updates of every user.

## Other rules

- **Privacy:** the program goes online only to download OCR models, to check
  for and download updates, and when the user opens the feedback form. Any
  new network use must be written in `PRIVACY.md` and
  `installer/privacy.txt` (SignPath Foundation requires it).
- **Code signing policy:** the "Code signing policy" section of `README.md`,
  `CODE_SIGNING.md` and the website footer must stay (SignPath Foundation).
- **Website** (`site/index.html`): published by the `pages` workflow when
  `site/` changes on `main`.
