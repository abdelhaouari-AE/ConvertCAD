# Packaging ConvertCAD — portable, installer, AppImage, .deb

Every download contains the whole program: the DWG converter (GNU LibreDWG) and the OCR
(RapidOCR + ONNX Runtime) with its built-in model — English, French and the other
Latin-script languages. Users install nothing else. The other OCR models (Arabic,
Cyrillic, Greek, Korean, Devanagari, Thai, Tamil, Telugu, maximum accuracy) are **not**
bundled: users download the ones they need from the program (see *OCR models* below).

| Download | Built by | Built on | Result in `dist/` |
|---|---|---|---|
| Windows portable (zip) | `scripts\build_exe.bat` | Windows 10/11 x64 | `ConvertCAD-<v>-win64-portable.zip` |
| Windows installer | `scripts\build_installer.bat` | Windows + Inno Setup 6.3+ | `ConvertCAD-<v>-win64-setup.exe` |
| Linux portable (tar.gz) | `scripts/build_linux.sh` | Ubuntu 22.04 or older | `ConvertCAD-<v>-linux-x86_64.tar.gz` |
| Linux AppImage | `scripts/build_appimage.sh` | same | `ConvertCAD-<v>-x86_64.AppImage` |
| Debian / Ubuntu package | `scripts/build_deb.sh` | same | `convertcad_<v>_amd64.deb` |

The GitHub workflow `.github/workflows/build.yml` builds all five and publishes them as the
GitHub release `v<version>`: *Actions → build → Run workflow* with **Publish the release**
ticked, or a pushed version tag (`git tag v1.2.0 && git push --tags`). The release is created
once both builds have succeeded, with the CHANGELOG section of the version as notes. The
website (https://abdelhaouari-ae.github.io/ConvertCAD/, folder `site/`) reads the newest
release when it opens, so its download buttons need no change.

## Windows

```bat
scripts\setup_venv.bat            :: once: .venv + libraries
scripts\build_exe.bat             :: portable folder + zip
scripts\build_installer.bat       :: installer (builds the program first if needed)
```

`build_exe.bat` installs the build tools, runs the tests, runs PyInstaller with
`ConvertCAD.spec`, signs (optional, see below) and zips. `build_exe.bat onefile` makes a
single `ConvertCAD.exe` instead (slower start).

**Portable mode:** an empty file `ConvertCAD.portable` next to `ConvertCAD.exe` keeps the
settings and the downloaded OCR models in that folder (USB stick). The installer never
installs that file.

### The installer (Inno Setup)

1. Install Inno Setup 6.3 or later: `winget install JRSoftware.InnoSetup`
   (or <https://jrsoftware.org/isdl.php>).
2. Run `scripts\build_installer.bat` (`rebuild` as argument to rebuild the program).

By hand: `ISCC.exe /DAppVersion=1.2.0 installer\ConvertCAD.iss`, after `build_exe.bat`.

What `installer\ConvertCAD.iss` does: installs `dist\ConvertCAD\` for the current user
without administrator rights (or for all users on request), wizard in English, French,
Spanish, German and — with Inno Setup 6.5 or later, which ships `Arabic.isl` — Arabic
(right to left; older versions simply leave Arabic out),
Start-menu shortcut, optional desktop shortcut and *Send to → ConvertCAD* entry, clean
upgrade (the old `_internal` folder is removed first), uninstaller in *Settings → Apps*.
The settings (`%USERPROFILE%\.convertcad`) are kept on uninstall; the downloaded OCR
models (`%LOCALAPPDATA%\ConvertCAD\ocr_models`) are removed (an upgrade keeps them).
Never change its `AppId`: it links new versions to installed ones. The script is UTF-8
**with a byte order mark** (it contains Spanish, German and Arabic texts): keep the mark
when editing it — without it Inno Setup reads the file as ANSI.

## Linux

```bash
./scripts/setup_venv.sh           # once
./scripts/build_linux.sh          # portable folder + tar.gz (builds LibreDWG the first time)
./scripts/build_appimage.sh       # AppImage (downloads appimagetool once)
./scripts/build_deb.sh            # .deb (needs dpkg-deb)
```

Build tools: `sudo apt install build-essential xz-utils` (LibreDWG) and the Qt runtime
libraries listed in `build.yml`. Build on the **oldest** distribution you want to support:
a program built against a recent glibc does not start on an older one (CI uses Ubuntu
22.04, glibc 2.35).

- **AppImage:** `chmod +x ConvertCAD-<v>-x86_64.AppImage`, then run it. `--cli` as first
  argument runs the command-line tool: `./ConvertCAD-1.2.0-x86_64.AppImage --cli plan.pdf -o plan.dwg`.
- **.deb:** `sudo apt install ./convertcad_<v>_amd64.deb` installs into `/opt/convertcad`
  with the commands `convertcad` and `convertcad-cli`, a menu entry, and pulls the few
  system libraries Qt needs.
- Downloaded OCR models go to `~/.local/share/convertcad/ocr_models` (all three formats).

## What goes into every build

| Part | Source | How it gets in |
|---|---|---|
| DWG converter | `vendor/libredwg/win64` (in Git) or `linux-x86_64` (built by `scripts/build_libredwg.sh linux`) | `ConvertCAD.spec` → `_internal/libredwg/` |
| OCR + built-in model (≈ 30 MB) | `rapidocr` + `onnxruntime` packages (model included) | `ConvertCAD.spec` |
| Other OCR models | not bundled: downloaded by the users | — (offline build: below) |

The Windows LibreDWG programs are cross-compiled on Linux:
`./scripts/build_libredwg.sh windows` (needs `gcc-mingw-w64-x86-64`). Only needed after a
change to `vendor/libredwg/patches/`.

## OCR models (downloaded from the program)

`convertcad/core/ocr_catalog.py` lists the downloadable models (packs), their files,
SHA-256 and sizes. The program downloads them into the user models folder
(`convertcad/core/ocr_store.py`): first from this repository's GitHub release
**`ocr-models-v1`**, then from RapidOCR's model repository (ModelScope) as a mirror. Each
file is checked against its SHA-256 before it is kept.

- **Publishing the release** — *Actions → OCR models release → Run workflow*
  (`.github/workflows/ocr-models.yml`): downloads every model from the mirror, checks it,
  test-runs it, and creates or updates the release (not marked *latest*, so the program
  releases stay first — until the first program release exists, GitHub still shows it as
  the latest). Run it once, then after any catalogue change.
- **Private repository** — release files of a private repository cannot be downloaded
  without signing in to GitHub, so users get the models from the mirror. Make the
  repository public (or host the files elsewhere and change `RELEASE_BASE`) to serve them
  from GitHub.
- **Offline build** (computers that must never go online):
  `python scripts/get_ocr_models.py --all --dest vendor/ocr_models` before building — the
  spec bundles that folder (about 200 MB more) and the program finds the models there.
- **Maintenance:** `python scripts/get_ocr_models.py --list` (catalogue),
  `--check DIR --load` (checksums + test run of every pack).

## Code signing (Windows)

The official downloads are signed by **SignPath Foundation** (free for open-source
projects): see [CODE_SIGNING.md](../CODE_SIGNING.md) for the policy and
[PRIVACY.md](../PRIVACY.md) for the privacy policy (shown by the installer, required by
SignPath).

How it works in `.github/workflows/build.yml` (job `windows`):

1. PyInstaller builds `dist/ConvertCAD/`; the smoke test runs.
2. `ConvertCAD.exe` and `ConvertCAD-cli.exe` are uploaded as an artifact and sent to
   SignPath (artifact configuration `app`, file `.signpath/artifact-configurations/app.xml`).
   The job **waits for the approval on signpath.io** (up to 1 hour), downloads the signed
   files and checks their signature.
3. The portable zip and the installer are made from the signed programs.
4. The installer is signed the same way (configuration `installer`), second approval.

Third-party programs (LibreDWG `dxf2dwg.exe` / `dwg2dxf.exe`) are not signed: SignPath
Foundation signs only binaries built from this project's own source.

One-time setup, after SignPath Foundation accepted the project:

- in SignPath: project slug `ConvertCAD`, signing policy `release-signing` (manual
  approval), GitHub as trusted build system, artifact configurations `app` and
  `installer` pasted from `.signpath/artifact-configurations/`, a CI user with an API token;
- in GitHub (Settings > Secrets and variables > Actions): secret `SIGNPATH_API_TOKEN`,
  variable `SIGNPATH_ORGANIZATION_ID`.

Without them the build simply produces unsigned programs. Signing on your own computer
with a certificate of your own is still possible with `scripts\sign_windows.bat`
(`CONVERTCAD_SIGN_PFX` / `CONVERTCAD_SIGN_THUMBPRINT`).

## Release checklist

1. Update `APP_VERSION` in `convertcad/__init__.py` and `CHANGELOG.md`.
2. `python -m pytest -q` and `python -m ruff check .`
3. Commit and push to `main`.
4. *Actions → build → Run workflow*, tick **Publish the release** (or push the tag
   `v<version>`). The release `v<version>` is created with the five downloads and the
   CHANGELOG section as notes; the website offers it at once.
5. Only when `ocr_catalog.py` changed: run the **OCR models release** workflow.
