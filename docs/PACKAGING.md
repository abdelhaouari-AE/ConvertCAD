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

The GitHub workflow `.github/workflows/build.yml` builds all five on every version tag
(`git tag v1.2.0 && git push --tags`) and attaches them to the GitHub release.

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

## Code signing (Windows, optional)

Unsigned programs work, but Windows SmartScreen shows "Windows protected your PC /
unknown publisher" the first time, until the download builds a reputation.
To sign, get an Authenticode code-signing certificate, then before building:

```bat
set CONVERTCAD_SIGN_PFX=C:\keys\convertcad.pfx
set CONVERTCAD_SIGN_PASSWORD=********
:: or, for a certificate in the Windows store / on a USB token:
set CONVERTCAD_SIGN_THUMBPRINT=0123456789ABCDEF0123456789ABCDEF01234567
```

`build_exe.bat` then signs `ConvertCAD.exe`, `ConvertCAD-cli.exe` and the LibreDWG
programs, and `build_installer.bat` signs the setup program
(`scripts\sign_windows.bat`, needs `signtool.exe` from the Windows SDK). In GitHub Actions,
add the secrets `SIGN_PFX_BASE64` (the .pfx, base64-encoded) and `SIGN_PFX_PASSWORD`.

Where to get a certificate:
- **SignPath Foundation** — free signing for open-source projects that meet its terms
  (public repository, OSI licence, builds from GitHub Actions); <https://signpath.org/>.
- A commercial certificate authority (Certum — which has a lower-cost open-source
  certificate —, Sectigo, DigiCert...). Since 2023 the private key must stay on a hardware
  token or a cloud signing service.
- Microsoft **Azure Artifact Signing** (formerly Trusted Signing, about 10 USD/month):
  at the time of writing only for individuals in the USA / Canada and organisations in the
  USA / Canada / EU / UK.

Check the current conditions with each provider.

## Release checklist

1. Update `APP_VERSION` in `convertcad/__init__.py` and `CHANGELOG.md`.
2. `python -m pytest -q` and `python -m ruff check .`
3. Commit, then `git tag v<version> && git push --tags`.
4. The **build** workflow attaches the five downloads to the release; edit the release
   notes (copy the CHANGELOG section).
5. Only when `ocr_catalog.py` changed: run the **OCR models release** workflow.
