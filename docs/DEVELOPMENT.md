# ConvertCAD — Development guide

Complete technical description of **ConvertCAD 1.2.0**: the programming language and
tools, the architecture and data flow, the content of every file, the algorithms, the
options, the tests, the build and release process, and how to extend the application.

*Author: abdelhaouari · Last update: 30 October 2026 · Applies to version 1.2.0*

How to build the downloads (portable, installer, AppImage, .deb) and sign them:
[PACKAGING.md](PACKAGING.md).

---

## Contents

1. [What ConvertCAD does](#1-what-convertcad-does)
2. [Technology stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Repository layout — what each file contains](#4-repository-layout--what-each-file-contains)
5. [The conversion engine (`convertcad/core`)](#5-the-conversion-engine-convertcadcore)
6. [The desktop interface (`convertcad/ui`)](#6-the-desktop-interface-convertcadui)
7. [The command-line tool](#7-the-command-line-tool)
8. [Options reference](#8-options-reference)
9. [Layers written in the DXF](#9-layers-written-in-the-dxf)
10. [Settings, logs and files on the user's computer](#10-settings-logs-and-files-on-the-users-computer)
11. [Languages (English, French, Spanish, German, Arabic)](#11-languages-english-french-spanish-german-arabic)
12. [Theme and icons](#12-theme-and-icons)
13. [Testing](#13-testing)
14. [Working in VS Code](#14-working-in-vs-code)
15. [Building the portable application and the installers](#15-building-the-portable-application-and-the-installers)
16. [Continuous integration and releases](#16-continuous-integration-and-releases)
17. [Extending ConvertCAD — recipes](#17-extending-convertcad--recipes)
18. [Performance notes](#18-performance-notes)
19. [Known limitations and roadmap](#19-known-limitations-and-roadmap)
20. [Licences](#20-licences)
21. [Version history](#21-version-history)

---

## 1. What ConvertCAD does

ConvertCAD reads a 2D PDF drawing (exported from AutoCAD, Revit, MicroStation, Tekla…, or
scanned) and writes a DXF or DWG file that a draughtsman can edit immediately in any CAD
software — the whole sheet or only a selected area.

The guiding principles, applied everywhere in the code:

| Principle | How it shows in the code |
|---|---|
| **Real CAD entities, not spaghetti** | Bezier curves become ARC / CIRCLE or one exact SPLINE; touching segments become one LWPOLYLINE; repeated symbols become BLOCKs; arrows + line + value become a DIMENSION (`geometry.py`, `annotations.py`, `blocks.py`). |
| **Never invent, never corrupt** | A dimension is rebuilt only when every part agrees (an angle or arc length only when its value agrees with the drawn arc); the value shown is always the original PDF text; unmatched measurement texts go to layer `DIM_RAW`; a texture hatch is kept only when the standard pattern drawn again reproduces the PDF pieces; traced scan content goes to `TRACE_*` layers with the scan kept underneath (`annotations.py`, `textures.py`, `raster.py`). |
| **Review before saving** | The interface converts into a private temporary folder; the user checks the DXF preview, the layers and the report, then saves (`postprocess.py`). |
| **One engine, many front-ends** | The interface, the command line, the folder batch and the tests all call `pipeline.convert()` with the same `Options` object. |
| **Local and portable** | Conversions never use the network (the only connections: downloading an OCR model, or checking for a newer version — off by default — when the user asks); the portable zip needs no installation; every download bundles its tools (DWG converter, OCR with its built-in model), settings and downloaded OCR models in the user profile or next to the program. |
| **Fast to open, fast to look at** | Heavy libraries load after the window shows (§18); the DXF preview merges thousands of primitives into a few hundred items. |
| **Maintainable by one person** | Pure-Python engine without Qt, small focused modules, plain dataclasses between steps, a test for every feature, comments that explain *why*. |

---

## 2. Technology stack

### 2.1 Programming language

**Python 3.10 or newer** (developed and tested with Python 3.13; CI also runs 3.10 and 3.12).

Why Python:

- the best open-source libraries for the three hard parts — reading PDF geometry
  (PyMuPDF), writing DXF (ezdxf) and image analysis (OpenCV) — are Python libraries;
- the heavy computing happens inside compiled C/C++ code (MuPDF, OpenCV, NumPy, Qt,
  ONNX Runtime), so Python is only the "glue" and stays fast enough (an A0 sheet with
  35 000 primitives converts in about 5 seconds; a dense A0 AutoCAD plot with 70 000
  dashes and hatch lines in about 20 seconds);
- the code stays readable and easy to modify for a beginner developer.

Language features used: dataclasses for every data structure passed between steps,
type hints (`typing.List`, `Optional`, …), f-strings, `multiprocessing` for the background
conversion, `argparse` for the command line, `json` for settings and reports.

### 2.2 Runtime libraries

Declared in [`requirements.txt`](../requirements.txt) and [`pyproject.toml`](../pyproject.toml).

| Library | Version (minimum → tested) | What ConvertCAD uses it for | Licence |
|---|---|---|---|
| **PySide6-Essentials** (Qt 6 for Python) | 6.6 → 6.12 | The whole desktop interface: main window, drawing viewers (`QGraphicsView`), panels, dialogs, style sheets, SVG icons, Markdown help pages, offscreen testing. | LGPL-3.0 |
| **PyMuPDF** (MuPDF) | 1.24.3 → 2.0 | Reading PDF vector paths (`get_drawings`, `get_cdrawings`), text spans with font size and colour, embedded images, page rotation; rendering pages for the viewer, thumbnails and scan tracing. | AGPL-3.0 or Artifex commercial |
| **ezdxf** | 1.3 → 1.4.5 | Creating the DXF document (R12 → R2018): layers, linetypes, LWPOLYLINE, ARC, CIRCLE, SPLINE, HATCH, TEXT, MTEXT, DIMENSION, MULTILEADER, BLOCK/INSERT, IMAGE; its *drawing add-on* renders the DXF preview. | MIT |
| **NumPy** | 1.26 → 2.5 | Least-squares circle fitting (Kasa method), image arrays for scan tracing. | BSD-3-Clause |
| **opencv-python-headless** | 4.8 → 5.0 | Scanned pages: adaptive binarisation, despeckling, probabilistic Hough lines, Hough circles. | Apache-2.0 (wrapper MIT) |
| **rapidocr** `[rtl]` | 3.10 | The OCR: PaddleOCR's PP-OCR detection / recognition models run with ONNX Runtime; whole text lines, small, rotated and vertical text. The built-in model is in the package (PP-OCRv6 small: Latin-script languages, Chinese, Japanese). `[rtl]` adds python-bidi for the reading order of Arabic. | Apache-2.0 (python-bidi LGPL-3.0) |
| **onnxruntime** | 1.20 → 1.31 | Runs the PP-OCR models on the CPU, offline. | MIT |
| **GNU LibreDWG** *(external programs `dxf2dwg`, `dwg2dxf`)* | 0.13.4 + 3 patches | DWG output (AutoCAD 2000 format) and its read-back check. Windows programs in `vendor/libredwg/win64`, Linux built by `scripts/build_libredwg.sh`; bundled in every download. | GPL-3.0-or-later |
| Downloadable PP-OCR models *(files, not bundled)* | PP-OCRv6 medium, PP-OCRv5 mobile | Maximum accuracy (Latin) and the other scripts (Arabic, Cyrillic, Greek, Korean, Devanagari, Thai, Tamil, Telugu), downloaded by the users from the program (§5.14). | Apache-2.0 |

ezdxf itself depends on `pyparsing`, `fonttools` and `typing_extensions` (installed
automatically).

### 2.3 Development tools

| Tool | Role | Where it is configured |
|---|---|---|
| **Visual Studio Code** | Editor, debugger, test explorer, tasks | [`.vscode/`](../.vscode) (settings, launch, tasks, recommended extensions) |
| Python extension + Pylance + debugpy | IntelliSense, type checking (basic), debugging (including the conversion child process) | `.vscode/settings.json`, `.vscode/launch.json` |
| **Ruff** | Linter (pycodestyle errors/warnings, pyflakes, bugbear) | `[tool.ruff]` in `pyproject.toml` |
| **pytest** | Test-suite (115 tests) | `[tool.pytest.ini_options]` in `pyproject.toml`, [`tests/`](../tests) |
| **venv + pip** | Isolated development environment `.venv/` | [`scripts/setup_venv.bat`](../scripts/setup_venv.bat) / `.sh` |
| **PyInstaller** | Builds the portable program (Windows and Linux) | [`ConvertCAD.spec`](../ConvertCAD.spec), [`scripts/build_exe.bat`](../scripts/build_exe.bat), [`scripts/build_linux.sh`](../scripts/build_linux.sh) |
| **Inno Setup** 6.3+ | Windows installer | [`installer/ConvertCAD.iss`](../installer/ConvertCAD.iss), [`scripts/build_installer.bat`](../scripts/build_installer.bat) |
| **appimagetool**, **dpkg-deb** | Linux AppImage and .deb | [`scripts/build_appimage.sh`](../scripts/build_appimage.sh), [`scripts/build_deb.sh`](../scripts/build_deb.sh), [`packaging/linux/`](../packaging/linux) |
| **gcc / MinGW-w64** | Builds the LibreDWG programs (Linux natively, Windows cross-compiled) | [`scripts/build_libredwg.sh`](../scripts/build_libredwg.sh) |
| **signtool** *(optional)* | Authenticode code signing | [`scripts/sign_windows.bat`](../scripts/sign_windows.bat) |
| **Git + GitHub** | Version control, issues, pull requests, releases | [`.gitignore`](../.gitignore), [`.gitattributes`](../.gitattributes), [`.github/`](../.github) |
| **GitHub Actions** | Tests on Windows and Linux at every push; the five downloads at every version tag | [`.github/workflows/`](../.github/workflows) |
| **EditorConfig** | Same indentation / line endings in every editor | [`.editorconfig`](../.editorconfig) |
| Qt "offscreen" platform | Runs the interface without a screen (tests, CI, screenshots) | `QT_QPA_PLATFORM=offscreen` |

### 2.4 Why these choices

- **Qt (PySide6) instead of Tkinter** (used up to version 2.1): Qt 6 is natively DPI-aware
  (no blurry text at 125 % / 150 % scaling), offers `QGraphicsView` for smooth zoom and pan on
  large drawings, real style sheets for a professional look, and runs offscreen for tests.
  PySide6 is the official Qt binding (LGPL), *Essentials* keeps the download small.
- **PyMuPDF** is the fastest PDF library for Python and gives the exact vector geometry
  (lines, Bezier curves, rectangles, dash arrays, colours, widths) plus a high-quality
  renderer, in one package.
- **ezdxf** is the most complete DXF library for Python: it writes real DIMENSION and
  MULTILEADER entities with their blocks, supports every DXF version and can render a DXF.
- **A separate process for conversions** instead of a thread: PyMuPDF is not thread-safe,
  a process can be cancelled instantly, and a crash in a native library cannot close the
  window (details in §3.2).
- **GNU LibreDWG for DWG** instead of the free ODA File Converter: the ODA converter may
  not be redistributed with other software (ODA Community User Agreement §3.1.1) and is for
  non-commercial use by non-members; LibreDWG is free software, so it ships inside every
  download and users install nothing (§5.15).
- **RapidOCR as the only OCR** (1.1): the same PP-OCR models as PaddleOCR, but run with
  ONNX Runtime (about 30 MB instead of about 1 GB for PaddlePaddle), and much better than
  Tesseract on drawings (whole lines, small, rotated and vertical text) — Tesseract and the
  PaddleOCR library were removed in 1.1.
- **One OCR model built in, the others downloaded** (1.1): the built-in model covers
  English, French and 45 other Latin-script languages (plus Chinese and Japanese) in about
  30 MB; bundling every script and the larger models would add about 200 MB to every
  download for the few users who need them.

---

## 3. Architecture

### 3.1 Layers of the application

```
  main.py ─────────────► convertcad/ui ──(JobRunner: child process)──┐
  python -m convertcad        PySide6 interface                     │
                                                                    ▼
  convertcad_cli.py ───► convertcad/cli.py ──(same process)──► convertcad/core
  python -m convertcad --cli    argparse → Options                  │  pure Python, never imports Qt
                                                                    │
                     pipeline.convert(pdf, dxf, Options, progress, should_cancel) → ConversionReport
                                                                    │
   extractor → raster (scans) → clip → geometry/patterns → layers → annotations → blocks
                                                → dxf_writer → report  (→ dwg: LibreDWG)
                                                                    │
       PyMuPDF · NumPy · OpenCV · RapidOCR (PP-OCR, ONNX Runtime)    ezdxf · LibreDWG
```

Dependency rules (keep them when you modify the code):

1. `convertcad/core` **never imports Qt**. It can run in a console, a server, a test or a
   child process.
2. The interface talks to the engine only through a few functions:
   `pipeline.convert` (via `jobs.JobRunner`), `pdfinfo.inspect_document` / `detect_scale`
   (before converting), `postprocess.layer_summary` / `finalize` (after converting),
   `presets.apply_preset` and the OCR model functions (`ocr.language_choices`,
   `ocr.pack_usable`, `ocr_store`: download, install, remove).
3. Every option is a field of `options.Options` (re-exported by `pipeline` and
   `convertcad.core`). The interface, the command line and the presets read and write that
   one dataclass.
4. The engine works in **page coordinates** (§3.5); only `dxf_writer.py` knows about the
   DXF axes, units and scale.

### 3.2 Process model

```
 GUI process (Qt event loop)                      Child process (multiprocessing, "spawn")
 ─────────────────────────────                    ───────────────────────────────────────
 MainWindow ── JobRunner.start_convert() ───────► jobs._child_convert()
     ▲              │                                 └─ pipeline.convert(...)
     │   QTimer polls the queue every 60–80 ms             │ progress(msg, frac)
     │              ▼                                      ▼
     └──── ("progress", msg, frac) ◄──── multiprocessing.Queue ◄──── q.put(...)
           ("done", ConversionReport)
           ("file", index, report)      (folder mode, one per file)
           ("error", traceback) / ("cancelled",)
```

- The child imports only `convertcad.core` — never Qt — so it starts quickly.
- **Cancel**: `JobRunner.cancel()` sets a `multiprocessing.Event` that `pipeline.convert`
  checks between steps (`should_cancel`); if the child has not stopped after 2.5 s it is
  terminated. The interface receives `("cancelled",)`.
- If the child dies (crash in a native library on a malformed PDF), `poll()` emits an
  `("error", …)` message: the window stays open and tells the user.
- Works in the frozen `.exe` because `main.py` calls `multiprocessing.freeze_support()`.
- The "spawn" start method is forced so behaviour is identical on Windows, Linux and macOS.

### 3.3 Conversion data flow (one page)

| Step | Module / function | Input → output |
|---|---|---|
| 0 | `pipeline.convert` | opens the PDF, checks password, selects pages, computes the scale, creates the `DxfWriter`(s); a `.dwg` target goes through `_convert_to_dwg` (step 8) |
| 1 | `extractor.extract_page` | PDF page → `PageData` (raw `RawSegment`, `RawBezier`, `RawFill`, `RawText`, `RawImage`, SHX texts, page kind) in displayed coordinates; letter outlines under invisible text removed |
| 1b | `raster.vectorize_page` + `merge_into_page` *(scanned pages only)* | page image → traced segments, circles and OCR texts (models chosen by `ocr.make_plan`) added to `PageData` |
| 1c | `clip.clip_page` *(selected area only)* | every primitive cut to `Options.clip_rect` |
| 1d | `pipeline._drop_white` | white strokes / texts dropped, white fills kept aside as masks |
| 1e | `pipeline._page_scale` | scale of this sheet: calibration › written on the sheet (`auto_scale`) › drawing scale |
| 2 | `geometry.rebuild` | `PageData` → `RebuiltPage` (`EPolyline`, `EArc`, `ECircle`, `ESpline`): duplicates removed, dashes merged and hatch lines grouped (`patterns.py`), then chaining |
| 3 | `layers.build_layer_table` (called by the writer) | styles → `LayerInfo` table (names, colours, lineweights, linetypes) |
| 4 | `annotations.reconstruct` | `RebuiltPage` + texts → `AnnotationResult` (dimensions, leaders, consumed entities, `DIM_RAW` texts) |
| 5 | `blocks.detect_blocks` | remaining entities → `BlockResult` (definitions + insertions with rotation / mirror) |
| 6 | `dxf_writer.DxfWriter.write_*` | everything above → DXF entities in model space |
| 7 | `pipeline._save` + `report.ConversionReport` | DXF file(s) + `<name>_log.txt`, report returned to the caller |
| 8 | `dwg.dxf_to_dwg` *(DWG output)* | AutoCAD 2000 DXF → cleaned DXF → LibreDWG `dxf2dwg` → DWG read back by `dwg2dxf` and checked |

Each step consumes plain dataclasses and returns plain dataclasses, so each one can be
tested alone (see `tests/test_extractor.py` … `tests/test_writer.py`).

### 3.4 Review-before-save workflow (interface)

1. `MainWindow` creates a private temporary folder (`tempfile.mkdtemp(prefix="convertcad_")`).
2. Each conversion writes into `…/runN/<name>.dxf` (+ `_log.txt`, + images if any).
3. The DXF preview (`dxf_view.py`), the layer table (`postprocess.layer_summary`) and the
   report are built from that temporary result.
4. The user's layer edits (keep / rename / recolour) are kept in memory
   (`layers_panel.LayerModel.edits`).
5. **Save DXF…** calls `postprocess.finalize(src, dst, edits, …)` in a background thread:
   the temporary DXF is read again, the edits are applied with ezdxf, image files are copied
   and re-linked to the new name, the log is copied with a summary of the edits appended,
   and the final DXF is written. **Save DWG…** calls `postprocess.finalize_dwg`: the same,
   then the DWG conversion (§5.15). A DWG needs an AutoCAD 2000 DXF: when the result was
   converted for another DXF version, the interface offers to convert again with the DWG
   format and saves when that conversion ends.
6. The temporary folder is deleted when the window closes.

The temporary result is never modified, so the user can change the edits and save again.

### 3.5 Coordinates, units and scale

| Space | Unit | Axes | Used by |
|---|---|---|---|
| PDF page (unrotated) | point = 1/72 inch = 0.3528 mm of paper | y down | PyMuPDF raw output |
| **Displayed page** | point | y down, page `/Rotate` applied | the whole engine, the viewers (scene units), the snap engine |
| DXF model space | mm, cm or m (`Options.units`) | y up | `dxf_writer.Transform` only |

- `compat.page_matrix(page)` maps unrotated to displayed coordinates, so the DXF looks exactly
  like the PDF on screen, whatever the page rotation.
- Units per point: `units.compute_scale(units, N, calibration)`:
  - with a paper scale 1:N → `0.352778 mm × N × unit factor` (factor 1 for mm, 0.1 for cm,
    0.001 for m);
  - with a calibration → the value measured by the user (real distance ÷ distance in points).
- `units.effective_denominator()` converts a calibration back to an equivalent 1:N, shown to the
  user as a sanity check ("about 1:100.2") and used for the DXF `$LTSCALE`.
- In *one DXF* mode, sheets are placed side by side with a gap of 10 % of the sheet width.
  `ConversionReport.placements` records where each sheet went (offset, scale, size, area)
  so the interface can lay the PDF exactly under the result (*Overlay*).
- A selected area (`Options.clip_rect`) is a rectangle in displayed page points, applied to
  every converted sheet; the DXF keeps the sheet's coordinates (the area is not moved to
  the origin), so several areas of one sheet line up.

### 3.6 Colours

- `dxf_writer.nearest_aci()` maps every RGB colour to the nearest **AutoCAD Color Index**:
  black and white become **ACI 7** (black on paper, white on a dark CAD screen), greys map to
  grey indices (8, 9, 250–254), other colours use a perceptual "redmean" distance.
- An entity gets colour **ByLayer** when its colour equals its layer's colour, so changing a
  layer colour in CAD recolours its entities — what a CAD manager expects.
- *True colour* mode keeps the exact RGB (R2004+), with the ACI as a fallback.

---

## 4. Repository layout — what each file contains

```
ConvertCAD/
├── main.py, convertcad_cli.py          launchers
├── convertcad/                         the Python package
│   ├── core/                           conversion engine (no Qt)
│   ├── ui/                             desktop interface (PySide6)
│   └── resources/                      Markdown texts shown in the app
├── tests/                              pytest suite
├── scripts/                            setup / run / build helpers
├── installer/                          Inno Setup script (Windows installer)
├── packaging/linux/                    desktop entry + AppImage launcher
├── vendor/libredwg/                    DWG converter: source, patches, Windows programs
├── docs/                               this guide, PACKAGING.md, screenshots
├── assets/                             application icon
├── samples/                            demonstration PDFs
├── .github/ .vscode/                   CI and editor configuration
└── ConvertCAD.spec, pyproject.toml, requirements*.txt, …
```

### 4.1 Root of the repository

| File | Content / role |
|---|---|
| `main.py` | Application launcher: `python main.py [drawing.pdf]`. Calls `multiprocessing.freeze_support()` (needed by the exe), checks the libraries when run from source (`convertcad/launcher.py`), then `convertcad.ui.app.run_gui()`. Imports stay inside `main()` so the conversion child process does not load the interface. Entry point of `ConvertCAD.exe`. |
| `ConvertCAD.pyw` | Same as `main.py` without a console window: double-click it on Windows to run from source. |
| `convertcad_cli.py` | Console launcher of the command-line tool; entry point of `ConvertCAD-cli.exe`. Without arguments it prints its help and waits (instead of closing at once). |
| `ConvertCAD.spec` | PyInstaller recipe: data files (resources, ezdxf, RapidOCR settings and its built-in model, LibreDWG programs, OCR models of `vendor/ocr_models` for an offline build), hidden imports, excluded modules, Windows version information, folder or single-file build, console twin (§15). |
| `pyproject.toml` | Project metadata (name, version read from `convertcad/__init__.py`, dependencies, licence, entry points `convertcad` / `convertcad-cli`), pytest and Ruff configuration. Allows `pip install -e .`. |
| `requirements.txt` | Runtime dependencies with minimum versions and a comment on each. |
| `requirements-dev.txt` | Runtime + development tools (pytest, PyInstaller, Ruff). |
| `README.md` | GitHub home page: features, screenshots, install, use, build, licence, French summary. |
| `CHANGELOG.md` | Version history (1.0.0 first public release, 1.1.0 OCR models, 1.2.0 curved dimensions, textures, five languages). |
| `LICENSE` | GNU Affero General Public License v3.0 (full text). |
| `THIRD_PARTY_NOTICES.md` | Licences of every library used or bundled. |
| `.gitignore` | Files Git must ignore: caches, `.venv/`, `build/`, `dist/`, test outputs (`*.dxf`, `*.dwg`, `*_log.txt`), the Linux LibreDWG build and the OCR models of an offline build (`vendor/ocr_models`). |
| `.gitattributes` | Line endings: LF for Python/Markdown/shell/patches, CRLF for `.bat` and `.iss`; binary files marked. |
| `.editorconfig` | UTF-8, 4-space indentation for Python, 100-character lines, CRLF for batch files. |

### 4.2 `convertcad/` — package root

| File | Content / role |
|---|---|
| `__init__.py` | `APP_NAME`, `APP_VERSION` (**the only place the version number is written**), `APP_AUTHOR`, `APP_YEAR`; package overview. |
| `__main__.py` | `python -m convertcad` opens the interface; `python -m convertcad --cli …` runs the command line. |
| `cli.py` | Command-line tool: argument parser (presets, every option, `--scale N\|auto`, pages, `--area`, `--format dxf\|dwg`, DXF version, `--ocr-lang`, `--ocr-quality`, `--list-ocr`, `--get-ocr-model`, JSON report, batch, quiet), `options_from_args()`, `parse_area()`, progress printers, exit codes 0/1/2. |
| `config.py` | `Settings` dataclass saved as JSON (theme, language — one of `i18n.LANGUAGES` —, recent files, folders, last options, user presets, snap modes, window layout, `check_updates`, off by default). Location: `~/.convertcad/` or `settings/` next to the exe in portable mode; atomic save; tolerant load; migration of the v1/v2 terms flag. |
| `launcher.py` | Start-up checks when running from source, standard library only: Python version, missing libraries (offers to install `requirements.txt` with pip, in the console or through a dialog under `pythonw`), and keeps a double-clicked console window open so messages can be read. Not used inside the exe. |
| `i18n.py` | Interface languages (§11): `LANGUAGES` (en, fr, es, de, ar), `tr()` (English text is the key; French in the `FR` dictionary, the other languages in `locales/`), `table(lang)`, `is_rtl()` (Arabic), `tr_progress()` (translates engine progress messages), `tr_paper()` (paper names), `set_language()`. |
| `locales/` | `es.py`, `de.py`, `ar.py`: one `STRINGS` dictionary {English text: translation} per language, loaded when the language is chosen. |
| `samples.py` | Draws the demonstration PDFs with PyMuPDF: an A3 formwork plan (*plan de coffrage*) at 1:100 with grid axes, columns, doors, tank, curved wall, spline, arrow and tick dimensions, leaders, notes, hatch, title block, plus a rotated second sheet; and a scanned version. Used by the welcome screen, the tests and `scripts/make_samples.py`. |

### 4.3 `convertcad/core/` — the conversion engine

| File | Content / role |
|---|---|
| `__init__.py` | Re-exports `convert`, `convert_folder`, `Options`, `Cancelled`, `ConversionReport`, `find_pdfs` — **lazily** (PEP 562 `__getattr__`): importing a light module such as `constants` does not load PyMuPDF, NumPy and ezdxf. |
| `constants.py` | Plain data shared by everything: point→mm factor, units table (`$INSUNITS` codes), paper scales offered, DXF versions, output formats, reserved layer names, layer naming modes, page modes, curve precision factors, OCR accuracy choices, scan resolutions. |
| `options.py` | `Options` — every option and its default (standard library only, so the settings panel builds at start-up without the conversion libraries); `from_dict()` (tolerant: old or partial presets never break), `writer_dxf_version()` (AutoCAD 2000 DXF for a DWG), `describe()` (options block of the log), `normalize_rect()`. |
| `units.py`, `stats.py`, `paths.py`, `layer_edits.py` | Light modules shared by the engine and the interface: `compute_scale()` / `effective_denominator()`; `WriteStats` (entity counters); `find_pdfs()` / `output_paths()`; `LayerEdit` / `LayerRow` / protected layers. |
| `compat.py` | Single import point for PyMuPDF (`import pymupdf`); blocks PyMuPDF 2.x's optional `pymupdf.layout` / `pymupdf4llm` add-ons (≈ 0.6 s faster start); `page_matrix()` (rotation), point/vector transforms, `library_versions()` for the About box and the log. |
| `spatial.py` | `GridIndex` (uniform-grid spatial index; `insert_path()` registers an arc or a circle along its outline only) and geometry helpers: point–segment and point–line distances, segment intersection, angles. Makes neighbourhood searches O(n) instead of O(n²). |
| `pdfinfo.py` | Quick inspection before converting: page kind (vector / scanned / empty) from path counts and image coverage, ISO paper size name, rotation, metadata, password, `detect_scale()` (reads "Echelle : 1/100", "SCALE 1:50", "Ech. 2.5:1000" → 1:400, a ratio alone above a scale bar; refuses fractions and sheets with several scales), thumbnails. |
| `extractor.py` | **Step 1.** Reads one page with PyMuPDF into raw dataclasses (`Style`, `RawSegment`, `RawBezier`, `RawFill`, `RawText`, `RawImage` with its placement matrix, `PageData`) in displayed coordinates; linetype classification from dash arrays; page classification; SHX texts placed on their letters (strokes moved to the hidden layer `TEXT_SHX_STROKES`); letter outlines lying under invisible text removed (`_drop_text_outlines`). |
| `raster.py` | **Step 1b.** Scanned pages: render, OCR through `ocr.py` (text-line boxes, horizontal or vertical, confidence and noise filters, text masking), adaptive binarisation, Hough circles validated against ink, arcs fitted on stroke outlines (`find_arcs`), Hough lines merged collinearly. |
| `ocr.py` | The OCR (PP-OCR models run by RapidOCR + ONNX Runtime, offline): `make_plan(languages, quality)` turns the user's choice into the models to run, falling back to the built-in model with a note for the report when a model is missing; `recognize(img, plan)`; `merge_script()` keeps, line by line, the reading of each script for mixed drawings (Latin + Arabic…); `available()`, `pack_usable()`, `language_choices()` (installed languages for the interface). |
| `ocr_catalog.py` | The OCR models ConvertCAD knows (*packs*): the built-in Latin model, the maximum accuracy models and one model per script, with their files, SHA-256, sizes and download addresses (GitHub release `ocr-models-v1`, then RapidOCR's repository); `language_set()` / `language_error()` parse the language keys (`latin`, `arabic`, `latin+arabic`, and the 1.0 codes `eng+fra+ara`…). Standard library only. |
| `ocr_store.py` | Where downloaded models live (user folder per operating system, portable mode, `CONVERTCAD_OCR_MODELS`), whether a pack is installed, `download_pack()` (streamed into a `.part` file, SHA-256 checked, then renamed; fallback address; progress; cancel), `install_files()` (offline installation, files recognised by checksum), `remove_pack()`. Standard library only. |
| `clip.py` | Selected area: Liang–Barsky segment clipping, Bezier subdivision clipping, Sutherland–Hodgman polygon clipping, `clip_page()`. |
| `geometry.py` | **Step 2.** Rebuilds CAD geometry: segment de-duplication, texture hatches (`textures.py`, before the dashed lines; zero-length dots kept for them; drawn boundaries snapped), dashed lines and hatch patterns (`patterns.py`), Kasa circle fit, Bezier→ARC, arc merging into ARC/CIRCLE, Bezier chains → one exact SPLINE, chaining into polylines, back-track collapse, collinear merge; tolerances in `Tol`. |
| `patterns.py` | What CAD plotters explode: `merge_dashed_lines()` (collinear pieces with a regular rhythm → one line with a measured linetype: DASHED, CENTER, DASHDOT, PHANTOM, DOT, DIVIDE), `detect_hatch_patterns()` (families of parallel, regularly spaced lines → `HatchPattern` with angle, spacing, boundary and holes; crossing grids), `add_mask_holes()` (white masks under texts become holes); tolerances in `PTol`. |
| `textures.py` | Texture hatches exploded by plotters (dots, sand, concrete, gravel, earth, brick, insulation): groups of dashes and dots compared with the standard patterns `TEXTURES` (scale from dash lengths or dot spacing, angle from directions, origin by vote), the pattern drawn again with ezdxf and kept only when it reproduces the PDF (§5.17); `TextureHatch`, `snap_boundaries()`. |
| `layers.py` | **Step 3.** Layer naming rules: native PDF layer names, role layers, style fingerprints (`GEO_BLACK_050_CENTER`), readable colour names (HSV), lineweight mapping, name sanitising. |
| `annotations.py` | **Step 4.** Recognises dimensions — radius and diameter (arrow on a circle along its radius + R/Ø value), angle and arc length (two arrows along an arc + a value that agrees with it), linear (arrowheads or oblique ticks + line + value, extension lines) — and leaders (arrow + polyline + note); safe fallback to `DIM_RAW`; tolerances in `ATol`. |
| `blocks.py` | **Step 5.** Clusters touching entities per layer (long lines cut into chunks, long elements excluded), computes fingerprints in the 8 orientations of a square (rotations by 90° and mirror images, `D4`), turns symbols repeated ≥ N times into block definitions + insertions with rotation / mirror (`insert_orientation()`); copies turned by any other angle matched by their key points (`_turned_copies`); tolerances in `BTol`. |
| `dxf_writer.py` | **Step 6.** `DxfWriter`: document setup (units, linetypes, text style, `$LTSCALE`), layers (hidden ones off), colours (ACI / true colour, ByLayer), polylines, arcs, circles, exact splines, solid and pattern hatches (`_USER` pattern with the measured angle and spacing), measured linetypes `CC_<FAMILY>_<n>`, images (exact placement and orientation), TEXT/MTEXT (cap height), SHX texts, rotated linear, radius, diameter, 3-point angular and arc-length DIMENSIONs with text override (ARC_DIMENSION exploded to its drawing before AutoCAD 2007 and for DWG), standard pattern HATCHes (textures) with the measured scale, angle and origin, MULTILEADER with multi-line notes (LEADER + MTEXT on old versions), rotated / mirrored block inserts, R12 fallbacks; `Transform` (page → DXF). |
| `pipeline.py` | Orchestration: `convert()` (never raises; progress and cancel callbacks; `.dwg` targets through `_convert_to_dwg`), area clipping, white strokes and masks, per-sheet scale, scanned-page handling, sheet placements for the overlay, output names (`_p2` suffixes in split mode), `convert_folder()` for batch mode. |
| `dwg.py` | Native DWG output: finds the bundled LibreDWG programs, prepares the DXF for LibreDWG's reader (post-2000 objects removed, MTEXT rotation, AutoCAD's handle numbering, linetype count, complete INSERT scale factors, group 16 of 3-point angular dimensions removed), runs `dxf2dwg`, reads the DWG back with `dwg2dxf` and checks entity count and block references (§5.15). |
| `report.py` | `ConversionReport`: inputs, options, results per entity type, layers (with block-internal counts), blocks, page notes, warnings, errors, status, duration; rendered as text (`_log.txt`), HTML (interface, translatable) and JSON. |
| `postprocess.py` | After conversion: `layer_summary()` (rows of the layer table), `apply_layer_edits()` (remove / rename-merge / recolour), `finalize()` (copy to the final path with edits, images and log), `finalize_dwg()` (same, saved as DWG), `needs_reconversion_for_dwg()`, `describe_edits()`. |
| `presets.py` | Six built-in presets (recommended, architectural, structural, scanned, geometry, CNC) and the functions that apply or store presets without touching drawing-specific values. |
| `jobs.py` | `JobRunner`: runs `convert` / `convert_folder` in a child process and relays progress, results, errors and cancellation through a queue (§3.2). |
| `updates.py` | Optional update check (off by default): one request to GitHub's public API for the releases, nothing sent, nothing installed; `check()`, `newest_release()` (the OCR models release is skipped), `is_newer()`, `UpdateError` (§5.18). |
| `licensing.py` | Licence hook: `check_license()` (called before every conversion) and `license_summary()` (About box). Always permissive; replacing this file adds licence management without touching anything else. |

### 4.4 `convertcad/ui/` — the desktop interface

| File | Content / role |
|---|---|
| `__init__.py` | Package docstring. |
| `app.py` | `run_gui()`: Qt application, high-DPI policy (fractional scaling passed through), Fusion style + theme, language (right-to-left layout for Arabic), app icon, logging to `convertcad.log`, global exception dialog, first-launch Terms gate, main window; `_warm_up()` loads the heavy libraries in a background thread once the window is shown; `CONVERTCAD_STARTUP_PROBE=1` prints the start-up time. |
| `main_window.py` | `MainWindow`: actions and shortcuts, menus, command bar, layout (sheets / viewers + activity / settings-layers-report tabs), status bar, open / inspect / hints, tools (measure, calibrate, select area), calibration and measurement, conversion through `JobRunner`, result loading, overlay check (PDF under the result, opacity slider), stale-options notice, saving DXF or DWG in a background thread (`_SaveThread`), batch, theme and language switching (*View > Language*, five languages), entity selection in the result (status text, layer selected), optional update check (`_UpdateThread`, Help menu), tool labels dropped when they do not fit (`_fit_toolbar`), drag & drop, recent files, window state, close handling. |
| `cadview.py` | `CadView`, base class of both viewers (always left to right, even in Arabic): CAD navigation (wheel zoom at cursor, middle-button / Space / Pan-tool drag), fit, zoom limits, `view_changed` and `zoom_changed` signals. |
| `pdf_view.py` | `PdfView`: source sheet on a "drafting table" with shadow; sharp at any zoom (base image + high-resolution tile of the visible area); Measure, Calibrate and Select-area tools (area: drag a rectangle, outside dimmed, size label, Esc cancels); snap glyphs and labels; crosshair; measurements drawn as dimension lines with ticks; calibration overlay; `format_length()`. |
| `dxf_view.py` | `DxfView`: renders the converted DXF with ezdxf's drawing add-on in a background `QThread` (`Recorder`); `merge_recording()` merges the primitives into one `QGraphicsPathItem` per layer set, colour, width, kind and tile (8 × 8), with cosmetic pens — a few hundred items instead of tens of thousands; hiding a layer stays instant; overlay of the PDF sheets (`set_overlay`, `set_overlay_opacity`); theme-aware background; **selection**: a pick index built after the preview is shown (`build_pick_index`, `PickIndex.pick`: nearest stroke within 5 screen px, else the smallest filled area under the cursor), highlight, `selected` signal with `describe_entity()` (type, layer, length, radius, text, block…). |
| `snap.py` | `SnapEngine` (Qt-free): endpoints, midpoints, intersections and centres computed once per page from PyMuPDF paths, stored in a `GridIndex`; `SnapHit`. |
| `pages_panel.py` | Sheet list: thumbnails rendered one by one on a timer, include checkbox, Vector / Scan / Empty badge with tooltip, paper size and rotation, selection menu (all, none, vector, scanned, invert), selected-sheets summary. |
| `options_panel.py` | `OptionsPanel`: preset selector (save / delete user presets), collapsible sections with every option and its tooltip (output format DXF / DWG, area *Select area… / Whole sheet*, OCR languages — installed ones only, a missing choice kept and marked *(not downloaded)* — and OCR accuracy, button *OCR languages and models…*), calibration status, OCR status line, "options changed" notice, conversion to / from `Options`. |
| `layers_panel.py` | `LayersPanel`: layer table (keep checkbox, bordered colour swatch, name + linetype on two lines, entity count), filter, show / hide all, undo all, kept-layers counter, `select_layer()` (the layer of the selected entity); edits applied at save time. |
| `report_panel.py` | `ReportPanel` (translated HTML report, save as `.txt` / `.html`, copy) and `ActivityPanel` (timestamped session log). |
| `statusbar.py` | `TitleBlockBar`: status bar drawn like a drawing title block — sheet, paper, scale or calibration, cursor X/Y in real units, snap toggles END/MID/INT/CEN, zoom, message, progress. |
| `empty_state.py` | Welcome screen: drop zone, *Open PDF…*, *Try the sample plan*, recent drawings, the four workflow steps. |
| `dialogs.py` | `MarkdownDialog` (renders `resources/*.md`), `GuideDialog`, `TermsDialog` (first-launch gate), `AboutDialog` (component versions including RapidOCR, ONNX Runtime, the installed OCR models and LibreDWG, licence status), `ShortcutsDialog`, `CalibrateDialog` (real distance input with validation). |
| `ocr_models_dialog.py` | `OcrModelsDialog` (*OCR languages and models…*): installed models (built in / downloaded / included) with *Remove*, drop-down list of the models to download with their size, *Download* with progress bar and *Cancel* (`DownloadWorker`, a `QThread`), *Install from file…* (offline computers), models folder, download page, help; `models_changed` signal; `stop_downloads()` at exit. |
| `batch_dialog.py` | `BatchDialog`: input / output folders, sub-folders, *read the scale on each sheet*, per-file status and time, progress, cancel, open output folder. |
| `widgets.py` | Reusable pieces: `PanelHeader` (title + small actions), `CollapsibleSection`, `Toast` (fading message), `small_button`, `label`, `hline`, `restyle`. |
| `theme.py` | Colour tokens for the dark and light themes, fixed markup palette, fonts, Qt palette and the complete style sheet; `apply_theme()`, `tok()`, `current()`. |
| `icons.py` | The original icon set (SVG line art on a 24 px grid) tinted at run time with the theme colour; the application icon `APP_ICON_SVG`; checkbox tick for the style sheet. |

### 4.5 `convertcad/resources/`

| File | Content |
|---|---|
| `guide_<lang>.md` (en, fr, es, de, ar) | User guide (Help → User guide, F1): workflow, navigation, snap, what the conversion produces, every setting, batch, checklist, troubleshooting. |
| `terms_<lang>.md` | Terms of use shown at first launch (local processing, user's rights, engineering responsibility, no warranty, settings). |
| `ocr_<lang>.md` | OCR guide (Help → OCR guide): languages (built in / downloaded / mixed scripts), accuracy, downloading, models folders per system, offline installation, command line, tips. |

Placeholders `{APP_VERSION}`, `{APP_AUTHOR}`, `{APP_YEAR}` are replaced when displayed. The
folder is bundled into the exe by `ConvertCAD.spec`.

### 4.6 `tests/`

| File | What it checks |
|---|---|
| `conftest.py` | Fixtures: the sample plan and scan (generated once per session), `pdf_factory` to draw tiny PDFs in a test, helpers `stroke()` and `arrow()`. No binary test file is stored. |
| `test_extractor.py` | Coordinates, page rotation, styles and dash arrays, text, page classification. |
| `test_patterns.py` | Dashed lines rebuilt (DASHED, CENTER, DOT), irregular pieces left alone, hatch patterns (diagonal, gratings), white-mask holes, pattern HATCH and measured linetype in the DXF, options off. |
| `test_sheet_features.py` | SHX comments (placed on the letters, strokes hidden; reviewer markups ignored), letter outlines under invisible text, scale reading (ratios, refusals), clipping (segments, polygons, Beziers, pages, pipeline). |
| `test_dwg.py` | DXF prepared for LibreDWG (handles, no duplicates), missing converter, DWG written and read back by the pipeline, rotated / mirrored blocks identical after the DWG round trip, INSERT scale completion (skipped when LibreDWG is not built). |
| `test_geometry.py` | Arc and circle fitting, arc merging, exact splines, polylines, duplicates, curve precision. |
| `test_annotations.py` | Arrow and tick dimensions, extension lines, leaders (text left or right), grid bubbles not taken as values, `DIM_RAW` fallback; radius, diameter, angle and arc length dimensions (values that disagree with the drawing are not rebuilt), written in R2018, R12 and DWG. |
| `test_textures.py` | Texture hatches recognised exactly (dots, gravel, earth, brick, insulation — scale, angle, pieces replaced), sand on its statistics, text and tile grids left alone, HATCH written with the drawn boundary, R12 keeps the lines, option off. |
| `test_blocks.py` | Repeated symbols become blocks; walls do not glue symbols; sample plan: doors ×3, columns ×20; rotated and mirrored copies (all 8 orientations) give exactly the drawn lines once the INSERTs are exploded; copies turned by any angle (and mirrored) become one block with the right rotations. |
| `test_writer.py` | Every DXF version, scale and units, ACI mapping, ByLayer, dimension angles, R12 fallbacks. |
| `test_pipeline.py` | End-to-end counts on the sample plan, options switched off, multi-page and split output, invalid pages, cancel, password, batch folder, per-sheet automatic scale. |
| `test_raster.py` | Scan tracing (OpenCV), arcs traced on a scan (centre, radius, span; a filled disc is not an arc) and written as ARC, OCR of the sample scan with the built-in model (skipped without RapidOCR), fallback to the built-in model when a model is missing, no OCR engine, mixed-script merge (Latin + Arabic), large sheets read at 150 dpi with boxes mapped back, engine settings (no orientation classifier for scripts, no 2000-px limit), ONNX Runtime telemetry off. |
| `test_ocr_store.py` | OCR catalogue consistency, language keys (including the 1.0 codes), models folder (environment variable, portable mode, Linux), download from a local web server: progress, checksum, fallback address, failure and cancel leave nothing behind; wrong-size files ignored; install from file and remove. |
| `test_postprocess.py` | Layer edits at save time (remove, rename-merge, recolour), images, log. |
| `test_cli_and_jobs.py` | Page ranges, CLI single / batch / errors, option mapping (including `--format`, `--area`, `--ocr-lang`, `--ocr-quality`), invalid OCR languages, presets keep the scale, background job runner (convert and cancel), `--scale auto`, `--list-ocr`, `--get-ocr-model`, options of version 1.0. |
| `test_i18n.py` | Every `tr("…")` string and menu action is translated in every language (French, Spanish, German, Arabic), as are the OCR catalogue names; no stale translation; placeholders survive translation; guides and terms exist in every language; Arabic is right to left; engine progress messages are translated. |
| `test_updates.py` | Version comparison, the check is off by default, one request with nothing about the user, the newest program release chosen (OCR models release, drafts and pre-releases skipped), failures reported. |
| `test_ui_smoke.py` | The real window offscreen: open the sample, convert in the child process, edit layers, save through the real save code, switch theme twice; select an area, convert, overlay on / off, save as DWG (with the automatic re-conversion); OCR languages list and status, *OCR languages and models…* window; selecting an entity in the result (layer selected, hidden layer clears the selection). |

### 4.7 `scripts/`

| File | Role |
|---|---|
| `setup_venv.bat` / `setup_venv.sh` | Create `.venv/` and install `requirements-dev.txt` (run once). |
| `run_from_source.bat` / `run_from_source.sh` | Start the application from the source (uses `.venv/` when present). |
| `build_exe.bat` | Build the portable Windows program: install tools → run tests → regenerate icon → PyInstaller → optional signing → zip (`onefile` argument for a single exe). |
| `build_installer.bat` | Windows installer with Inno Setup (builds the program first when needed), optional signing. |
| `sign_windows.bat` | Authenticode signing with `signtool` when a certificate is configured (does nothing otherwise). |
| `build_linux.sh` | Build the portable Linux program (`dist/ConvertCAD/ConvertCAD` + tar.gz), LibreDWG built the first time. |
| `build_appimage.sh`, `build_deb.sh` | Linux AppImage and Debian package from `dist/ConvertCAD/`. |
| `build_libredwg.sh` | Build the LibreDWG programs from the vendored source + patches (`linux`, or `windows` with MinGW-w64). |
| `get_ocr_models.py` | Maintainers: list the OCR catalogue, download packs (SHA-256 checked) — into the user folder, `vendor/ocr_models` for an offline build, or `release/` for the GitHub release (`--mirror-only`) —, `--check DIR --load` (checksums + test run), `--notes` (release description). |
| `make_icon.py` | Render `APP_ICON_SVG` to `assets/icon.svg`, `icon.png` and a multi-size `icon.ico` (16–256 px) with Qt only. |
| `make_samples.py` | Write `samples/sample_plan.pdf` and `samples/sample_scan.pdf`. |

### 4.8 Other folders

| Folder | Content |
|---|---|
| `assets/` | `icon.svg`, `icon.png`, `icon.ico` (generated by `make_icon.py`; the `.ico` is used by PyInstaller). |
| `samples/` | `sample_plan.pdf` (vector, 2 sheets) and `sample_scan.pdf` (150 dpi image) to try the app and the CLI. |
| `docs/` | `DEVELOPMENT.md` (this file), `PACKAGING.md` (building and signing the downloads) and `screenshots/` used by the README. |
| `installer/` | `ConvertCAD.iss`, the Inno Setup script of the Windows installer. |
| `packaging/linux/` | `convertcad.desktop` (menu entry) and `AppRun` (AppImage launcher, `--cli` switch). |
| `vendor/libredwg/` | GNU LibreDWG 0.13.4 source tarball, `patches/` (3 fixes), `win64/` Windows programs, `COPYING`, `README.md`, `SOURCE.txt`; `linux-x86_64/` is built locally (not in Git). |
| `vendor/ocr_models/` | Only for an offline build: downloadable OCR models bundled with the program (not in Git). |
| `site/` | The website (GitHub Pages): `index.html` (one static page, its CSS and script inside) and `img/` (screenshots, icon, social preview image). |
| `.github/workflows/` | `tests.yml` (lint + tests, Windows and Linux, Python 3.10 / 3.12 / 3.13, LibreDWG built and cached on Linux), `build.yml` (Windows portable zip + installer, Linux tar.gz + AppImage + .deb, as artifacts, then one release job), `pages.yml` (publishes the website), `ocr-models.yml` (publishes the downloadable OCR models as the release `ocr-models-v1`). |
| `.github/` | Issue templates (conversion problem, feature request) and pull-request checklist. |
| `.vscode/` | `settings.json`, `launch.json` (app, sample, CLI, current-PDF, tests), `tasks.json` (setup, tests, lint, samples, icon, builds), `extensions.json`. |

---

## 5. The conversion engine (`convertcad/core`)

### 5.1 `pipeline.convert()` — the single entry point

```python
from convertcad.core import convert, Options

report = convert("plan.pdf", "plan.dxf",
                 Options(scale_denominator=100, units="mm"),
                 progress=lambda message, fraction: print(message),
                 should_cancel=lambda: False)
print(report.status_word(), report.stats.total_entities(), report.outputs)
```

- **Never raises.** Errors are collected in `report.errors` (page-level failures do not stop
  the other pages) and warnings in `report.warnings`.
- Progress messages are English sentences ("Page 1/2: rebuilding geometry…"); the interface
  translates them with `i18n.tr_progress()`.
- `licensing.check_license()` is called first (hook for future licence management).
- `Options.page_mode = "split"` writes `<name>_p1.dxf`, `<name>_p2.dxf`… (one writer per
  page); `"single"` places the sheets side by side in one DXF.
- A target ending in `.dwg` (or `Options.output_format = "dwg"` in batch mode) converts to an
  AutoCAD 2000 DXF in a private folder, then to DWG next to the requested path (§5.15). If
  the DWG cannot be written, the DXF is saved there instead and the report says why.
- `convert_folder()` converts every PDF of a folder (optionally recursive) into a mirrored
  folder structure, each with its own log, and returns a summary.

### 5.2 Step 1 — `extractor.py`

- `page.get_drawings()` returns paths made of items `l` (line), `c` (cubic Bezier), `re`
  (rectangle), `qu` (quad). Each item becomes a `RawSegment` or `RawBezier` carrying a
  `Style` (RGB colour, width in points, dash array, linetype, PDF layer name, fill).
- Filled paths become `RawFill` polygons (Bezier outlines flattened) — candidates for HATCH
  or arrowheads. White fills and page-sized backgrounds are flagged so they can be ignored
  (they would hide the drawing in CAD).
- Text comes from `page.get_text("dict")`: spans with origin, size, angle (direction
  vector), colour and font; `RawText` exposes width, centre and direction helpers.
- `classify_linetype()` reads the *shape* of the dash array: equal dashes → DASHED; a long
  dash with short ones → CENTER (one short) or PHANTOM (two shorts); otherwise DASHDOT.
- Everything is transformed by `compat.page_matrix()` so coordinates are in the displayed
  orientation.
- **SHX texts.** AutoCAD draws SHX fonts as vector strokes and adds an invisible comment
  ("AutoCAD SHX Text", a Square annotation) holding the string. `_shx_texts()` reads the
  comments (title containing "SHX"; in AutoCAD PDFs also invisible read-only boxes — never a
  visible reviewer markup), finds the strokes lying inside each box, and places the text on
  them: left edge, baseline and letter height measured on the strokes, several lines and
  vertical text handled. The strokes move to `TEXT_SHX_STROKES`, a layer written *off*, so
  the drawing shows the real text once and the strokes stay available.
- **Letter outlines.** Some exporters draw TrueType text as filled outlines plus the same
  text invisible (render mode 3, for searching). `_drop_text_outlines()` removes the fills
  lying inside the invisible spans (box extended along the reading direction, because the
  drawn font often runs longer), so the DXF gets one editable text instead of a pile of
  filled shapes.
- Images keep their placement matrix (`RawImage.matrix`), so rotated or mirrored logos are
  written with the right orientation.

### 5.3 Step 1b — `raster.py` (scanned pages)

1. Render the page in grayscale at `raster_dpi` (capped by `MAX_RASTER_PIXELS` for huge
   sheets).
2. OCR (when enabled) with the models chosen by `ocr.make_plan()` (§5.14), on the page
   reduced to `RTol.OCR_DPI` (150 dpi, the resolution PP-OCR reads drawing text best at;
   at least 2000 pixels on the long side):
   whole text lines with their boxes (a line much taller than wide is vertical text, written with a
   90° rotation); results kept above a confidence threshold and with enough alphanumeric
   characters (noise filter); recognised boxes are erased from the image so letters are
   not traced. The models used are written in the report ("N OCR text(s) (PP-OCR: …)").
3. Adaptive threshold + small-component removal.
4. `find_circles()`: `HoughCircles` on the lightly smoothed image in two radius bands —
   up to `CIRCLE_SPLIT_R` (100 px) at full resolution, larger circles on a copy reduced to
   1/3 (strokes thickened first), then moved to their best full-resolution position — and
   each candidate kept only when ink covers `CIRCLE_COVER` (70 %) of its perimeter within
   1 px and `CIRCLE_EXACT` (50 %) exactly (vectorised checks; the exact check rejects the
   false circles that the speckles of poor scans would make). A single full-resolution search over 8–400 px took 4–5 min on an A1
   sheet; this takes seconds.
5. `find_arcs()`: each stroke outline (OpenCV contour, lightly smoothed) is simplified
   (`ARC_EPS`); runs of corners that bend a little (< `ARC_TURN`), always the same way, are
   fitted by a circle (algebraic fit + Gauss-Newton; a line leaving the arc on its tangent
   is trimmed off until the circle fits). An arc is kept only when the other side of the
   stroke gives the same circle (radius one stroke width apart, `ARC_PAIR`) — the outline
   of a filled area or a speck never does —, with at least `ARC_MIN_SWEEP`, `ARC_MIN_LEN`,
   a visible bend (`ARC_SAG`) and a radius of 4 pt or more (not the bowls of letters).
   Pieces of one circle cut by crossing strokes are joined. Arcs are masked before the
   line search and enter the page as Beziers (`arc_beziers`), so the rebuild makes them
   ARCs like vector arcs.
6. `HoughLinesP`, then `merge_collinear()` joins overlapping / touching collinear pieces.
7. `merge_into_page()` adds the results to `PageData` on layers `TRACE_LINES` /
   `TRACE_TEXT`, so the rest of the pipeline (polylines, dimensions, blocks) works unchanged.
   The scan itself is kept as an image on the locked `IMG_RASTER` layer.

When a scanned PDF already contains a text layer (searchable PDF), that text is used
instead of OCR (`use_pdf_text_layer`).

### 5.4 Step 2 — `geometry.py`

- **Arcs.** For each Bezier, sample points and fit a circle with the Kasa algebraic least
  squares method (`fit_circle`, NumPy). Accept the ARC when the maximum deviation is below
  `ARC_FIT_DEV` (0.08 pt), relaxed proportionally for large radii and multiplied by the
  *curve precision* factor (fine 0.5×, normal 1×, loose 2×).
- **Arc merging.** Arcs sharing style, centre and radius are grouped (union-find); their
  angular intervals are united; a union covering ≥ 358.5° becomes a CIRCLE, contiguous pieces
  become one ARC.
- **Splines.** Remaining Beziers that touch end to end (same style) are chained. A chain of
  *n* cubic Beziers is written as one clamped cubic B-spline whose interior knots have
  multiplicity 3 — an **exact** representation, not an approximation.
- **Textures, dashes and hatch lines first.** After de-duplication, `textures.detect_textures()`
  (§5.17; the zero-length segments — the dots of dotted patterns — are kept for it), then
  `patterns.merge_dashed_lines()` and `patterns.detect_hatch_patterns()` (§5.13) take the
  pieces CAD plotters explode, so they are not chained into meaningless polylines. Once the
  polylines exist, a closed outline that follows a texture's measured outline becomes its
  hatch boundary (`snap_boundaries`).
- **Polylines.** Zero-length and duplicated segments are removed (`dedupe_segments`), then
  segments sharing endpoints and style are chained (`chain_segments`) into LWPOLYLINEs,
  closed when they loop; A→B→A back-tracks collapse; redundant collinear vertices are
  removed (circular mean of doubled angles, so direction does not matter).
- Endpoint matching uses a hashed grid (`_qk`, `_neighbors`) — linear time.

### 5.5 Step 3 — `layers.py`

Priority: native PDF layer (OCG) name → role layer (text, hatch, dimension…) → style
fingerprint according to `layer_mode`:

| Mode | Example | Use |
|---|---|---|
| `style` | `GEO_BLACK_050_CENTER` (colour + lineweight ×100 mm + linetype) | default, mirrors how drawings are structured |
| `color` | `GEO_BLACK` | fewer layers |
| `single` | `GEOMETRY` | CNC / laser |

Colour names come from HSV (`BLACK`, `DKGRAY`, `RED`, `DKGREEN`, `CYAN`…). Lineweights snap
to the nearest DXF lineweight enum. Names are sanitised for AutoCAD (`<>/\":;?*|=` removed).

### 5.6 Step 4 — `annotations.py`

**Arrow dimensions.** Small filled triangles (`ARROW_MIN_AREA`–`ARROW_MAX_AREA`) are
arrowheads; the tip is the sharpest vertex. Arrow pairs pointing in opposite directions
along a common axis (bucketed by `_axis_key` for speed) are candidates. A pair becomes a
dimension only when a **measurement text** sits along the segment between the tips
(`_nearest_dim_text`). Extension lines are searched conservatively (`_find_extension`):
roughly perpendicular, passing through the tip, overshooting by at most `EXT_OVERSHOOT`, the
long side at least twice the short side — shared extension lines are reused by chained
dimensions (`ext_ids`). The DXF dimension is a rotated linear dimension at the exact angle
of the tips, its definition points on the extension lines, and the **PDF text kept as text
override**.

**Tick dimensions** (architecture): short oblique strokes (25°–75° to the dimension line)
at both ends of a line, with a value — same rules, written with architectural ticks.

**Radius and diameter** (`_radial_dimensions`, run first): an arrow whose tip lies on a
circle or an arc (`ON_CIRCLE`, or 2 % of the radius) and which points along the radius
(`RADIAL_DEG`), inwards or outwards; its value is an `R…` or `Ø…` text (`RADIUS_RE`,
`DIAMETER_RE`, also `2xØ12`, `%%c60`) within `RADIAL_TEXT` heights of the radius line, or
of the line drawn from the arrow (walked like a leader, landing included — its corner is
kept as `kink`). A diameter consumes the opposite arrow; the plain lines along the radius /
diameter are consumed, centre lines never. `RadialDimension` → `add_radius_dim` /
`add_diameter_dim` with the arrow exactly at the PDF tip and the text along the line or
horizontal as in the PDF.

**Angle and arc length** (`_angular_dimensions`): arrows lying on an arc and pointing
along it (`TANGENT_DEG`) are grouped by dimension arc (same centre and radius,
`TRACK_TOL`); two arrows pointing in opposite senses, with the arc drawn under both, give
two candidate spans (arrows inside: the span between them; arrows outside: the same arc
seen the other way). A value near the arc decides, and must agree with the drawing —
never invent: an angle (`45°`, `30°15'`, `ANGLE_RE`) within `ANGLE_AGREE` (2° or 4 %) of
the span; an arc length written with `⌒`, or a number that matches the arc length
measured on the concentric arc it dimensions × the page scale (`units_per_pt`) within
3 %, in mm, cm or m. `AngularDimension` → `add_angular_dim_3p` (extension lines not drawn:
the PDF ones stay) or `add_arc_dim_3p`. These run before the linear dimensions: two
nearly opposite arrows on a flat arc would otherwise pass for a linear dimension.

**Leaders**: an arrowhead whose shaft starts at the tip **or at the base** of the arrow
(plotters often stop the line at the arrow base, `_leader_start`); the shaft is followed
through up to `LEADER_HOPS` joined pieces (`_walk_leader`); the note is the text sitting
**on** the landing, or just **under** it, else the nearest one within reach
(`_landing_texts`), with several lines kept together. Direction words of stairs and ramps
("UP", "DN", "MONTEE"…), big titles and texts lying along the shaft are not notes. Written
as MULTILEADER (multi-line content, top-left anchored, underline connection, dogleg from
the shaft to the text edge) or LEADER + MTEXT for R12–R2004.

**Safety.** Texts that look like measurements but matched nothing go to `DIM_RAW`. Grid
bubble numbers and item marks (`_is_label`: a single character, or a text inside a small
circle) are not treated as values. Consumed lines, fills and texts are marked so they are not written twice.

### 5.7 Step 5 — `blocks.py`

1. **Clustering**, per PDF layer (or per colour): each entity is approximated by small boxes
   (`_pieces`; long lines cut into 12-pt chunks); boxes closer than `CLUSTER_GAP` are joined
   with union-find on a grid. Entities longer than 6 % of the page diagonal (beams, walls,
   axes) never join a cluster, so they cannot glue neighbouring symbols together; clusters
   of more than `MAX_CLUSTER` entities are layout, not symbols.
2. **Fingerprint.** For each cluster: entity types, style signature and coordinates relative
   to the cluster centre, quantised to 0.25 pt, sorted → a hashable key — computed in the 8
   orientations of the square (`D4`: rotations by 0/90/180/270° and their mirror images);
   the smallest key is the cluster's canonical fingerprint, its orientation is remembered.
3. **Blocks.** A fingerprint seen at least `block_min_repeats` times (default 3) with at
   least 2 entities becomes a block definition `CC_SYMBOL_nnn`; each occurrence becomes an
   INSERT on layer `BLOCKS` with the rotation and mirror (`xscale = -1`) that map the
   definition onto it (`insert_orientation()`, computed in DXF axes: y flipped on both
   sides). Block content keeps its original style layers. `block_rotations = False`
   restricts blocks to identical orientations.
4. **Any other angle** (`_turned_copies`): the clusters left alone by the fingerprints
   (fewer than N copies) are described by their key points — polyline vertices, arc
   centres and ends, circle centres, spline control points, each with its kind, style
   and radius — around their mean point. Clusters with the same kinds of points and the
   same sorted distances (± 2 × `TURN_TOL`) are compared: the farthest point of one is laid
   on each point of the other at the same distance, and the turn (or mirror + turn) that
   lays every point on a point of the same kind within `TURN_TOL` is refined by least
   squares on all the points. Groups of N or more become a block whose base point is the
   mean point; the INSERT rotation is the opposite of the page angle (y flipped).

### 5.8 Step 6 — `dxf_writer.py`

- `WriterSettings` (DXF version, units, layer mode, colour mode, text height ratio,
  effective scale, fill filters) and `DxfWriter` (one per output file).
- `_setup_document()`: linetypes (DASHED, CENTER, DASHDOT, PHANTOM, HIDDEN), text style,
  `$INSUNITS`, `$MEASUREMENT` (metric), `$LUNITS`, `$LTSCALE` (10 × N × unit factor, updated
  by `set_ltscale()` when a sheet scale is read), `$PSLTSCALE`.
- Rebuilt dashed lines get a linetype measured on the PDF (`_measured_linetype`:
  `CC_<FAMILY>_<n>`, element lengths divided by `$LTSCALE`), so they plot exactly as in the
  PDF at the drawing's linetype scale.
- Hatch patterns are written as pattern HATCH entities: a `_USER` pattern with the
  measured angle and spacing, the base point of the PDF lines, the outer boundary and the
  holes (white masks under texts); solid fills stay SOLID hatches.
- Every geometric entity goes through `Transform` (flip Y, scale, offset) — the only place
  where page points become real units.
- Text height = the measured cap height when known (SHX texts), else font size ×
  `text_height_factor` (cap height ≈ 0.70 × font size).
  Stacked lines of the same style are grouped by `group_text_lines()` into MTEXT
  (attachment top-left).
- Linear dimensions: `msp.add_linear_dim(base, p1, p2, angle, text=PDF value,
  dimstyle="Standard", override={arrow/tick size, text height, colours…})` — the sizes
  come from `_dim_override()`, shared by every kind of dimension.
- Radius / diameter: `add_radius_dim` / `add_diameter_dim` with `location` on the PDF line
  (text aligned with it, or horizontal with a landing); angle: `add_angular_dim_3p` (the
  y flip reverses the angles: DXF p1 = PDF end point); arc length: `add_arc_dim_3p`, kept
  as ARC_DIMENSION from R2007, otherwise exploded to its drawing on layer DIM
  (`_explode_dimension`; LibreDWG does not know ARC_DIMENSION). A failed ezdxf call leaves
  nothing behind (`_undo_from`).
- Texture hatches (`_write_textures`): `set_pattern_fill(name, scale = units per point ×
  pattern scale, angle, definition = ezdxf's acadiso.pat copy)` and the pattern base
  points moved to the measured origin.
- Blocks are defined once and inserted with `add_blockref` (rotation, `xscale = -1` for
  mirrored copies).
- Images: corners computed from the PDF placement matrix (`_image_corner`), so `u_pixel` /
  `v_pixel` carry rotation and mirror.
- R12: no LWPOLYLINE (POLYLINE 2D), no SPLINE (approximated polyline), no true colour, no
  MTEXT, classic LEADER, no pattern HATCH and no texture hatch (the lines are kept). R12 and R2000 use ACI
  colours.
- `WriteStats` counts every entity type and per-layer entities (including entities inside
  block definitions) for the report.

### 5.9 `report.py`

`ConversionReport.render()` writes the plain-text log (inputs, options, results, layers,
blocks, page notes, warnings, errors, status, duration, engineering checklist).
`to_html(dark, t)` produces the interface report; `t` is the translation function so the
panel follows the interface language while the engine stays language-neutral.
`to_json()` exports everything (used by `--json`).

### 5.10 `postprocess.py`

- `layer_summary(dxf)` → rows (name, RGB, ACI, linetype, entity count incl. blocks, locked).
- `apply_layer_edits(doc, edits)`: *remove* deletes the layer's entities everywhere
  (model space and block definitions) and the layer; *rename* moves entities to the new
  name — merging into an existing layer when the name is already used; *recolour* sets the
  layer colour (ACI or true colour according to the colour mode). Protected layers (`0`,
  `DEFPOINTS`) are never removed.
- `finalize()` writes the final DXF, copies and re-links raster images, copies the log and
  appends the list of edits. `finalize_dwg()` finalises into a private folder, converts that
  DXF to DWG (§5.15), copies the images and writes the log with a DWG note.

### 5.11 `spatial.py`

`GridIndex(cell)` stores items by bounding box in a dictionary of grid cells; queries return
the items of the cells overlapping a box or near a point. Cell size is chosen per use
(arrow search radius, snap radius, cluster gap). Pure Python, no dependency.

### 5.12 `jobs.py`, `presets.py`, `licensing.py`, `pdfinfo.py`, `compat.py`, `constants.py`

Described in §3.2, §4.3 and their module docstrings. Built-in presets:

| Preset | Changes from the defaults |
|---|---|
| Recommended (all features) | none |
| Architectural plans | tick dimensions on, MTEXT on, style layers, blocks from 2 repeats |
| Structural / formwork plans | dimensions + ticks, linetypes, blocks from 3 repeats |
| Scanned archive drawings | tracing + OCR, 400 dpi, no block detection |
| Geometry only | no dimensions, leaders, blocks or MTEXT |
| CNC / laser | R12 DXF, single layer, no PDF layers, no text, no hatch (solid or pattern), no annotations, no blocks, no images |

Built-in presets never change the scale, units, *read the scale on each sheet*, pages,
selected area or calibration.

### 5.13 `patterns.py` — exploded linetypes and hatch patterns

AutoCAD and other plotters often write a dashed line as hundreds of separate dashes, and a
hatch as hundreds of parallel lines. Kept as they are, they bloat the DXF (the DPP sample
sheet had 26 445 dash pieces) and cannot be edited.

- **Dashed lines** (`merge_dashed_lines`): pieces of the same style are grouped by line
  (direction, offset); along each line, runs of pieces separated by gaps of at most
  `MAX_GAP` are tested for a **regular rhythm** (the same sequence of dash / gap lengths
  repeating). Recognised families: DASHED, CENTER (long, gap, short, gap), DASHDOT,
  PHANTOM, DOT (dots only), DIVIDE. A run becomes one segment from the first to the last
  piece, with the measured pattern in `Style.dash_pattern` (`pt:12,-2,2,-2`). Irregular
  collinear pieces (walls with door openings) are left alone.
- **Hatch patterns** (`detect_hatch_patterns`): segments are grouped by style and angle;
  a family of parallel lines with a constant spacing (`MIN_SPACING`–`MAX_SPACING`) and
  enough rows (`MIN_ROWS_OBLIQUE` = 6, `MIN_ROWS_AXIS` = 12 for horizontal / vertical lines,
  so stair treads and title-block rows stay lines) becomes a `HatchPattern`: angle,
  spacing, origin, boundary (outline of the line ends) and holes. Two crossing families on
  the same area (`_pair_grids`, at least `MIN_GRID_ROWS`) make a grating.
- `add_mask_holes()`: white fills inside a hatch boundary (masks under texts) become
  holes, so the text stays readable in CAD.

### 5.14 `ocr.py`, `ocr_catalog.py`, `ocr_store.py` — OCR models

One engine — PaddleOCR's PP-OCR models run by **RapidOCR + ONNX Runtime**, on the CPU,
offline — and models in *packs* (`ocr_catalog.PACKS`):

| Pack | Models | Reads | Where it comes from |
|---|---|---|---|
| `latin` (built in) | PP-OCRv6 *small* detection + recognition (in the `rapidocr` package) | English, French and 45 other Latin-script languages, Chinese, Japanese | bundled (≈ 30 MB) |
| `latin_max` | PP-OCRv6 *medium* detection + recognition (132 MB) | the same, slightly better on poor scans, about 20 times slower (A1 test sheet: 83 % of the labels instead of 81 %) | download |
| `arabic`, `cyrillic`, `greek`, `korean`, `devanagari`, `thai`, `tamil`, `telugu` | one PP-OCRv5 *mobile* recognition model each, 8 MB (Korean 13 MB); the detection model is shared | that script | download |

Why PP-OCR, and why one built-in model: on drawings PP-OCR detects text *lines* anywhere,
small, rotated or vertical, even crossed by lines — far better than Tesseract (removed in
1.1). The built-in model covers the users' main languages; the others are one click away
instead of making every download about 200 MB larger.

- **The user's choice** is a *language key* (`Options.ocr_lang`): `latin`, a script
  (`arabic`), or `latin+<script>` for mixed drawings, plus an accuracy
  (`Options.ocr_quality`: `standard` | `maximum`). `ocr_catalog.language_set()` parses it
  (1.0 settings such as `eng+fra+ara` are mapped: `latin+arabic`).
- **`make_plan(languages, quality)`** → an `OcrPlan`: the detection model (built-in or
  medium) and one recognition *pass* per pack. A missing pack never stops the conversion:
  the built-in model is used and a note goes to the report.
- **`recognize(img, plan)`** runs the first pass, then each script pass; `merge_script()`
  keeps the script reading where a line is mostly in that script (Unicode ranges of the
  pack) and removes the Latin reading of the same place. RapidOCR puts Arabic back in
  reading order with python-bidi.
- RapidOCR instances are cached per model set; models given by path are never downloaded
  by RapidOCR itself. The script models run **without** RapidOCR's "upside-down text"
  classifier: it was trained on Chinese and Latin text and turns Thai, Devanagari and
  Arabic lines over (measured: unreadable with it, correct without it).
- **Resolution**: `raster._run_ocr` hands the OCR the page at `RTol.OCR_DPI` (150 dpi;
  small sheets keep at least `OCR_MIN_SIDE` = 2000 pixels on their long side) and
  RapidOCR's own size limit is raised to 8000 pixels. RapidOCR shrinks every image to
  2000 pixels by default and crops the text from that reduced image, so large sheets lost
  their small text (measured on an A1 sheet with 260 labels of 1.8–3.5 mm: 31–44 % read at
  2000 pixels, about 80 % at 120–150 dpi, no gain above).
- **No telemetry**: ONNX Runtime records usage data (program path, operating system,
  processor, a device identifier) in `~/.cache/Microsoft/DeveloperTools/.onnxruntime` and
  uploads it to Microsoft — on Linux too (seen with version 1.31). `convertcad/__init__.py` sets
  `ORT_DISABLE_TELEMETRY=1` before anything can import the library (it is read at import
  time; `disable_telemetry_events()`, also called, comes too late on its own). Keep it
  first if you reorganise the start-up code.
- **`ocr_store`**: models folder (`user_models_dir()`: `%LOCALAPPDATA%\ConvertCAD\ocr_models`,
  `~/.local/share/convertcad/ocr_models`, `~/Library/Application Support/ConvertCAD/ocr_models`,
  `<program>/ocr_models` in portable mode, or `CONVERTCAD_OCR_MODELS`); models are also
  looked for in `<program>/ocr_models` and `_internal/ocr_models` (offline build). A file
  only counts when its size matches the catalogue (interrupted copies are ignored).
- **Downloads** (`download_pack`): GitHub release `ocr-models-v1` first, RapidOCR's
  repository (ModelScope) second; streamed in 256 KB blocks into `<name>.part` while the
  SHA-256 is computed, renamed only when it matches; progress and cancel callbacks; system
  certificates + certifi; proxy from the system / `HTTPS_PROXY` (urllib). Only the model
  file is requested; no drawing or user data is ever sent.
- **Offline installation** (`install_files`): `.onnx` files copied from anywhere are
  recognised by their SHA-256, whatever their name.
- **Adding a language**: add a pack to `PACKS` (file name, path under the mirror, SHA-256
  from RapidOCR's `default_models.yaml`, size, `lang_type` = RapidOCR `LangRec` member,
  Unicode ranges), its English label and languages to `i18n.py` (French), run the *OCR
  models release* workflow, and the interface lists it automatically.

### 5.15 `dwg.py` — native DWG output

ConvertCAD writes the drawing as an **AutoCAD 2000 DXF** (every entity DWG 2000 can hold:
no MULTILEADER, ACI colours), then converts it with **GNU LibreDWG**:

1. `_clean_with_ezdxf()`: removes the post-2000 objects and dictionaries ezdxf adds, writes
   MTEXT rotations as a direction vector (LibreDWG rejects group 50 on MTEXT).
2. `_remap_handles()` (text level): gives *Model_Space the handle AutoCAD uses (0x1F) and
   the symbol tables their standard handles (LAYER 2, STYLE 3, LTYPE 5…), moves every other
   handle clear of the reserved range, updates `$HANDSEED`; `_fix_ltype_count()` counts the
   LTYPE table like AutoCAD (without ByBlock / ByLayer); `_complete_insert_scales()` writes
   the three scale factors of every scaled INSERT.
3. `dxf2dwg --as r2000` writes the DWG (the file must start with `AC1015`).
4. **Check**: `dwg2dxf` reads the DWG back; the entity count must not drop
   (`count_dxf_entities`) and every block reference must keep its position, scale and
   rotation (`insert_transforms`). Otherwise the DWG is refused with a clear message.

LibreDWG 0.13.4 needed three fixes in its DXF reader, kept as patches in
`vendor/libredwg/patches/` and applied by `scripts/build_libredwg.sh`:

| Patch | Bug fixed |
|---|---|
| `01-ltype-control-entries` | every linetype was listed twice in the DWG linetype table (LibreCAD refused the file) |
| `02-dxf-read-string-speed` | `strlen()` of the whole rest of the file for each character read: a 10 MB DXF took 4 minutes, now 9 seconds |
| `03-point-keeps-own-values` | a point given without its Y / Z (the scale of a mirrored block: X = -1 only) took the Y / Z of the previous point — blocks stretched hundreds of times |

The DWGs were validated with LibreDWG's own reader and with libdxfrw (LibreCAD's
independent DWG reader): same entities, layers, blocks and linetypes as the DXF.

**Why not the ODA File Converter?** It is the best-known free DWG converter, but its
licence does not allow shipping it inside another program, and it is for non-commercial use
by non-members of the Open Design Alliance. Users would have to install it themselves.
LibreDWG (GPL-3.0) is shipped inside every download.

### 5.16 `clip.py` — converting a selected area

`clip_page(pd, rect)` cuts every primitive of the page to the rectangle, in place:
segments with Liang–Barsky, Beziers by recursive subdivision (pieces fully inside kept,
neighbouring pieces merged), filled polygons with Sutherland–Hodgman; texts and SHX texts
kept when their origin is inside, images when they overlap. The page then goes through the
normal pipeline: only what is in the area is rebuilt, recognised and written, in the
sheet's own coordinates.

### 5.17 `textures.py` — texture hatches

AutoCAD plots a pattern hatch as one line per dash and one zero-length line per dot. Sand,
concrete, gravel, earth, brick, insulation and dotted areas therefore arrive as thousands
of tiny pieces. `detect_textures(segments)` (called by `geometry.rebuild` before the dashed
lines) works in page points with y turned up, like the DXF, so angles and the handedness
of the patterns are the DXF ones:

1. **Groups.** Per style (colour, width, PDF layer), the short pieces (≤ `XTol.SHORT`)
   and dots are grouped on a coarse raster (connected areas), with a link distance of
   2.5 × the usual gap between pieces, then 2× and 4× that for sparse patterns (bricks).
   A group must repeat a few shapes (`_repetitive`: mostly dots, or ≤ 60 distinct dash
   lengths covering 70 % of the pieces) — text strokes and details do not.
2. **Area.** The pieces are drawn on a raster, closed (1.6 × the gap) and outlined
   (`_Region`: outer polygon, holes, "inside, away from the edge" test).
3. **Candidates.** For each standard pattern of `TEXTURES` (DOTS, AR-SAND, AR-CONC,
   GRAVEL, EARTH, BRICK, AR-B816, AR-BRSTD, INSUL) whose share of dots fits
   (`DOT_SHARE`): its reference is drawn once at scale 1 (`reference()`: signature, dash
   lengths, repeat distance). Scale: the most common PDF dash length ÷ each pattern dash
   length, refined by all matched dashes (dots: ratio of the gaps). The density must
   agree. Angle: circular correlation of the direction histograms (dots: directions to
   the neighbours); the histograms must agree once turned.
4. **Origin.** On a window around the group's centre, every pair (PDF piece, pattern
   piece of the same kind) votes for the shift between them; the most voted shift must
   gather at least half of the pieces.
5. **Check (never invent).** The pattern is drawn again over the group's box with that
   scale, angle and origin (ezdxf's `hatching.hatch_entity` on a virtual HATCH); away
   from the edges, ≥ 90 % of the PDF pieces must be pattern pieces (same middle and
   direction) and ≥ 85 % of the pattern pieces must be in the PDF (long brick courses:
   checked along their length, inside the area). Sand and concrete look random and repeat
   only over long distances: when their exact position cannot be found, their statistics
   must agree instead (density, share of dots, gaps, lengths, directions) and the report
   says that their scale and position were estimated.
6. **Result.** The best pattern gives a `TextureHatch` (name, scale, angle, origin,
   boundary, holes); its pieces — including the pieces cut by the edge and the brick
   courses — are removed. `snap_boundaries()` later replaces the measured outline by a
   closed outline of the drawing that follows it. `XTol.TIME_BUDGET` (8 s per page) stops
   the search on pathological pages: the rest stays as lines.

The writer turns a `TextureHatch` into a HATCH with the standard pattern (`pattern_type`
predefined, ezdxf's copy of `acadiso.pat`) at the measured scale and angle, its base
points moved to the measured origin. R12 has no HATCH: the option is off there and the
pieces stay lines.

### 5.18 `updates.py` — optional update check

Off by default. *Help > Check for updates…* (or the startup option) calls `check()` in a
`QThread`: one GET of `https://api.github.com/repos/abdelhaouari-AE/ConvertCAD/releases`
with only `ConvertCAD/<version>` as User-Agent. `newest_release()` keeps the highest
version tag (`v1.2.0`) and skips drafts, pre-releases and the OCR models release
(`ocr-models-v1`, which GitHub may call "latest" — the reason the list is read instead of
`releases/latest`); that version is compared with `APP_VERSION` (`is_newer`). Nothing is
downloaded or installed: the interface shows the number and can open the release page.
Any failure is reported (`UpdateError`), never fatal; while the repository is private the
API answers 404 ("no published release").

---

## 6. The desktop interface (`convertcad/ui`)

### 6.1 Window layout

```
 menu bar        File · View · Tools · Help
 command bar     Open PDF ▾ | Pan · Calibrate scale · Measure distance · Select area |
                 Fit · − · + | Convert · Save DXF/DWG · Convert a folder | Theme · Help
 ┌ Sheets ─────┐┌ Source PDF | DXF result ───────────────┐┌ Settings | Layers | Report ┐
 │ thumbnails  ││ drawing viewer (zoom, pan, tools)       ││ options / layer table /    │
 │ badges      ││─────────────────────────────────────────││ conversion report          │
 │ selection ▾ ││ Activity log                            ││                            │
 └─────────────┘└─────────────────────────────────────────┘└────────────────────────────┘
 status bar      Sheet | Paper | Scale | Cursor X/Y | Snap END MID INT CEN | Zoom | message
```

All three columns and the activity panel are in splitters; their sizes and the window
geometry are saved in the settings. Panels can be hidden from *View → Panels*.

### 6.2 Workflow and state

`MainWindow._update_state()` enables actions and chooses the **one primary action**
(highlighted in teal) according to the state:

| State | Primary action | Notes |
|---|---|---|
| No drawing | *Open PDF…* | welcome screen (`empty_state.py`) |
| Drawing open | *Convert* | scale hint shown when read from the title block |
| Converting | *Convert* becomes *Cancel* (red) | progress in the status bar and activity log |
| Result ready | *Save DXF…* (or *Save DWG…* when the output format is DWG) | DXF result and Layers tabs shown; *Overlay PDF* available; window title marked ● until saved |
| Options changed after converting | *Convert again* | "options changed" notice in Settings |
| Saved | *Save DXF…* stays available | layer edits can be changed and saved again |

The **area** is drawn on the Source PDF with *Select area* (A): drag a rectangle; the
outside is dimmed and the size shown; *Whole sheet* (Settings › Scale, units and area)
removes it. It applies to every converted sheet and is not saved with the settings (it
belongs to one drawing).

Closing the window or opening another drawing with an unsaved result asks for confirmation.

### 6.3 Viewers

- **`CadView`** (base): `QGraphicsView` in scene units = page points; wheel zoom anchored
  at the cursor; pan with the middle button, Space + drag, or the Pan tool; `fit()`; zoom
  limits relative to the fit scale.
- **`PdfView`**: the sheet is rendered once at a moderate resolution (base image) and, when
  the view settles, the *visible area only* is re-rendered at screen resolution (detail
  tile) — sharp at 3 000 % zoom without rendering a gigantic image. Tools: *Measure*
  (two clicks, result drawn as a dimension line with ticks and value) and *Calibrate*
  (two clicks + real distance in `CalibrateDialog`). With snap on, `SnapEngine` returns the
  nearest END / MID / INT / CEN point within a screen radius and the AutoCAD glyph is drawn
  (square, triangle, cross, circle) with its name.
- **`DxfView`**: the DXF written by the engine is read and drawn by ezdxf's own renderer, in
  a background thread (`Recorder`). Still in that thread, `merge_recording()` merges the
  primitives into a few hundred `QGraphicsPathItem`s — one per layer set, colour, width,
  kind and tile of an 8 × 8 grid — drawn with **cosmetic pens** (constant screen width):
  the 40 000-entity DPP sheet gives about 650 items instead of 64 000 and repaints in
  20–30 ms. Items still know their layers, so unticking a layer hides it immediately. This
  shows the *CAD interpretation* of the file (true dimensions, blocks, linetypes), not the
  PDF.
- **Selection in the result** (read-only): once the preview is shown, `build_pick_index()`
  turns the recorded primitives into NumPy arrays of segments and filled areas, each with
  its top-level entity (`LayerRecorder` notes which entity draws what; dashed lines are
  added with their true geometry so a click in a gap still hits them). A click (a mouse
  move of at most 4 px) picks the nearest stroke within 5 screen pixels, else the smallest
  filled area under the cursor (images last), skipping hidden layers. The entity is
  highlighted (halo + core pens in the theme's selection colour), the status bar shows its
  type, layer, length / radius / text / block / pattern and size, and its layer is selected
  in *Layers*. Hiding its layer clears the selection.
- **Overlay check** (*Overlay PDF*, O): the source sheets are rendered (at most 4 000 px)
  and laid under the result at the place recorded in `ConversionReport.placements`, with an
  opacity slider; any difference between the PDF and the CAD result shows at once.

### 6.4 Panels and dialogs

See §4.4 for each file. Design rules used throughout:

- every option has a plain-language tooltip; long combo boxes are stacked under their
  label so no text is clipped in French;
- the narrow panels use compact actions (menus, icon buttons with tooltips);
- the layer table shows the full layer name (elided in the middle when too long) with the
  linetype as a caption, and bordered swatches so white layers stay visible (shown black on
  the light theme, as CAD software does with colour 7);
- messages appear as a short toast over the viewer and in the activity log.

### 6.5 Keyboard shortcuts

| Action | Shortcut | Action | Shortcut |
|---|---|---|---|
| Open PDF | Ctrl+O | Pan tool / cancel | Esc |
| Convert / stop | Ctrl+Enter | Calibrate | C |
| Save DXF / DWG | Ctrl+S | Measure | M |
| Select area | A | Overlay the PDF on the DXF | O |
| Convert a folder | Ctrl+B | Clear measurements | Del |
| Close the drawing | Ctrl+W | Object snap on/off | F3 |
| Fit the sheet | F | Next / previous sheet | Page Down / Page Up |
| Zoom in / out | Ctrl++ / Ctrl+− | Source PDF / DXF result | Ctrl+1 / Ctrl+2 |
| User guide | F1 | Exit | Ctrl+Q |

---

## 7. The command-line tool

Same engine, same options, no interface:

```bat
python -m convertcad --cli plan.pdf                         :: scale read on the sheet
python -m convertcad --cli plan.pdf -o out\plan.dxf --scale 100 --units mm
python -m convertcad --cli plan.pdf --calibrate 35.2778     :: real units per PDF point
python -m convertcad --cli plan.pdf --pages 1-3,5 --split-pages --dxf-version R2013
python -m convertcad --cli plan.pdf -o plan.dwg                 :: native DWG
python -m convertcad --cli plan.pdf --area 20,30,420,290        :: rectangle in mm on the sheet
python -m convertcad --cli scan.pdf --ocr-lang latin+arabic --ocr-quality maximum
python -m convertcad --cli drawings\ -o dwg\ --format dwg --recursive --preset structural
python -m convertcad --cli --list-presets
python -m convertcad --cli --list-ocr                           :: OCR models: installed / to download
python -m convertcad --cli --get-ocr-model arabic latin_max     :: download OCR models
```

In the portable build, `ConvertCAD-cli.exe` accepts exactly the same arguments. Without
`--scale`, the scale written on each sheet is used (`auto`), 1:50 (or the preset's value)
when none is found — the log says which scale each sheet received.

| Argument | Meaning |
|---|---|
| `input` | PDF file, or folder (batch mode) |
| `-o, --output` | DXF or DWG file, or output folder in batch mode (default: next to the PDF); a `.dwg` name selects the DWG format |
| `--format dxf\|dwg` | output format (default: from `-o`, else DXF) |
| `--area X0,Y0,X1,Y1` | convert only this rectangle of each sheet, in mm on the paper from the sheet's top-left corner |
| `--preset NAME` | start from a built-in preset |
| `--options-json FILE` | JSON object with `Options` fields (e.g. saved from Python) |
| `--scale N\|auto`, `--units mm\|cm\|m`, `--calibrate U` | scale and units |
| `--pages`, `--split-pages`, `--dxf-version`, `--layer-mode`, `--true-color` | output |
| `--no-arcs`, `--no-polylines`, `--no-text`, `--no-mtext`, `--no-hatch`, `--no-hatch-patterns`, `--no-dashes`, `--no-block-rotations`, `--no-dims`, `--no-ticks`, `--no-leaders`, `--no-blocks`, `--no-pdf-layers`, `--no-linetypes`, `--no-raster`, `--no-ocr`, `--no-images`, `--no-shx`, `--no-log` | switch features off |
| `--min-repeats N`, `--precision fine\|normal\|loose` | blocks, curve fitting |
| `--ocr-lang KEY` (`latin`, `arabic`, `latin+arabic`…), `--ocr-quality standard\|maximum`, `--dpi` | scanned pages |
| `--list-ocr` | list the OCR models (built in, installed, available), the models folder and the `--ocr-lang` keys |
| `--get-ocr-model ID [ID…]` | download OCR models (progress on stderr; exit code 1 if one failed, 2 if unknown) |
| `--recursive` | include sub-folders |
| `--json FILE` | write the report(s) as JSON |
| `-q, --quiet` | no progress lines |

Exit codes: **0** every file converted, **1** at least one failure, **2** invalid arguments
or input not found.

---

## 8. Options reference

All options are fields of `convertcad.core.options.Options` (also importable from
`convertcad.core` and `convertcad.core.pipeline`). Defaults below are the engine defaults
(the interface remembers the last values used).

| Field | Default | Interface (Settings tab) | CLI | Effect |
|---|---|---|---|---|
| `pages` | all | Sheets panel checkboxes | `--pages` | 1-based page numbers to convert |
| `clip_rect` | none | Scale, units and area › Select area… / Whole sheet | `--area` | rectangle `[x0, y0, x1, y1]` in displayed page points; only that part of each sheet is converted |
| `units` | `mm` | Scale and units › Units | `--units` | DXF unit (`$INSUNITS`) |
| `scale_denominator` | 50 | Scale and units › Drawing scale | `--scale N` | paper scale 1:N |
| `auto_scale` | off (CLI: on) | Scale › Read the scale written on each sheet | `--scale auto` | per-sheet scale from the title block, fallback 1:N |
| `calibrated_units_per_pt` | 0 | Calibrate tool | `--calibrate` | > 0 overrides every scale |
| `fit_arcs` | on | Geometry › Rebuild arcs and circles | `--no-arcs` | Bezier → ARC / CIRCLE |
| `join_polylines` | on | Geometry › Join segments into polylines | `--no-polylines` | LWPOLYLINE instead of LINEs |
| `join_splines` | on | Geometry › Join curves into single splines | — | one SPLINE per Bezier chain |
| `curve_precision` | `normal` | Geometry › Curve precision | `--precision` | arc-fit tolerance ×0.5 / ×1 / ×2 |
| `hatches` | on | Geometry › Solid fills as hatches | `--no-hatch` | filled areas → HATCH |
| `hatch_patterns` | on | Geometry › Rebuild hatch patterns | `--no-hatch-patterns` | parallel hatch lines → pattern HATCH (§5.13); textures → standard pattern HATCH (§5.17) |
| `merge_dashes` | on | Geometry › Rebuild dashed lines | `--no-dashes` | separate dashes → one line with a measured linetype |
| `ignore_white_fills`, `ignore_background_fills` | on | Geometry › Ignore white masks, white lines and page backgrounds | — | skip masks and white elements that would show in CAD |
| `text_entities` | on | Text › Export text | `--no-text` | TEXT entities |
| `group_mtext` | on | Text › Group stacked lines (MTEXT) | `--no-mtext` | paragraphs |
| `text_height_factor` | 0.70 | Text › Text height ratio | — | cap height ÷ font size |
| `shx_comments` | on | Text › Recover text drawn as strokes or outlines | `--no-shx` | SHX texts on layer `TEXT_SHX` (strokes on the hidden `TEXT_SHX_STROKES`), letter outlines under invisible text removed |
| `dimensions` | on | Dimensions › Arrow dimensions | `--no-dims` | true DIMENSIONs (linear, radius, diameter, angle, arc length) |
| `tick_dimensions` | on | Dimensions › Tick dimensions | `--no-ticks` | architectural ticks |
| `leaders` | on | Dimensions › Leaders | `--no-leaders` | MULTILEADER / LEADER |
| `use_pdf_layers` | on | Layers › Keep the PDF's layers | `--no-pdf-layers` | OCG names |
| `layer_mode` | `style` | Layers › Layer naming | `--layer-mode` | style / color / single |
| `recognize_linetypes` | on | Layers › Recognise linetypes | `--no-linetypes` | CENTER, DASHDOT… |
| `color_mode` | `aci` | Layers › Colours | `--true-color` | ACI or true colour |
| `block_detection` | on | Layers › Detect repeated symbols | `--no-blocks` | BLOCK + INSERT |
| `block_min_repeats` | 3 | Layers › Minimum occurrences | `--min-repeats` | threshold |
| `block_rotations` | on | Layers › Also match rotated and mirrored copies | `--no-block-rotations` | INSERT with rotation (any angle) / mirror |
| `raster_mode` | on | Scanned › Trace lines, circles and arcs | `--no-raster` | OpenCV tracing |
| `ocr` | on | Scanned › Read text with OCR | `--no-ocr` | OCR of scanned pages |
| `ocr_lang` | `latin` | Scanned › OCR languages | `--ocr-lang` | `latin` (English, French…), a script (`arabic`, `cyrillic`, `greek`, `korean`, `devanagari`, `thai`, `tamil`, `telugu`) or `latin+<script>` for mixed drawings (§5.14); 1.0 codes such as `eng+fra+ara` are accepted |
| `ocr_quality` | `standard` | Scanned › OCR accuracy | `--ocr-quality` | `standard` (built-in model) or `maximum` (larger models, downloaded; 1.0's "Maximum — PaddleOCR" engine maps to it) |
| `raster_dpi` | 300 | Scanned › Scan resolution | `--dpi` | 200–600 |
| `use_pdf_text_layer` | on | Scanned › Use the PDF's text layer | — | skip OCR on searchable scans |
| `include_images` | on | Scanned › Keep raster images | `--no-images` | locked `IMG_RASTER` |
| `output_format` | `dxf` | Output › File format | `--format`, `-o name.dwg` | DXF, or DWG (AutoCAD 2000 format, written from an AutoCAD 2000 DXF) |
| `dxf_version` | `R2018` | Output › DXF version | `--dxf-version` | R12 … R2018 (ignored for DWG) |
| `page_mode` | `single` | Output › Multi-page output | `--split-pages` | side by side / one file per sheet |
| `page_gap_factor` | 1.10 | — | — | spacing between sheets |
| `write_log` | on | Output › Write a conversion log | `--no-log` | `<name>_log.txt` |

`Options.from_dict()` ignores unknown keys and fills missing ones with defaults, so old
settings files and presets never break after an update.

---

## 9. Layers written in the DXF

| Layer | Content |
|---|---|
| `GEO_<COLOUR>_<WEIGHT>[_<LINETYPE>]` | geometry by style (mode *style*), e.g. `GEO_BLACK_050`, `GEO_GRAY_025_CENTER` |
| PDF layer names | geometry of PDFs that contain layers (OCG), when *Keep the PDF's layers* is on |
| `GEOMETRY` | all geometry (mode *single*) |
| `TEXT` | texts and MTEXT paragraphs |
| `TEXT_SHX` | texts recovered from AutoCAD SHX comments |
| `TEXT_SHX_STROKES` (off) | the strokes AutoCAD drew for those texts, kept but hidden |
| `DIM` | true DIMENSION entities (and the drawing of arc-length dimensions before DXF 2007 / in DWG) |
| `DIM_RAW` (red) | measurement texts that matched no dimension — **review them** |
| `ANNOT_LEADER` | leaders / multileaders |
| `HATCH` | solid fills; rebuilt hatch patterns and textures stay on the layer of their lines |
| `BLOCKS` | block references (INSERT); block content keeps its style layers |
| `TRACE_LINES`, `TRACE_TEXT` | geometry traced and text read on scanned pages |
| `IMG_RASTER` (locked) | embedded images and original scans, for checking |

---

## 10. Settings, logs and files on the user's computer

| What | Where | Content |
|---|---|---|
| Settings | `%USERPROFILE%\.convertcad\settings.json` — or `settings\settings.json` next to the exe when a file `ConvertCAD.portable` is present | theme, language, recent files, folders, last options, user presets, snap modes, window layout, terms acceptance |
| Application log | same folder, `convertcad.log` | start-up information and unexpected errors (with traceback) |
| Icon cache | same folder, `icons\` | checkbox tick SVG used by the style sheet |
| Temporary results | system temp folder, `convertcad_*` | conversions under review; deleted when the window closes |
| Conversion outputs | chosen by the user | `<name>.dxf` or `<name>.dwg`, `<name>_log.txt`, `<name>_pN_imgK.png` (raster images) |

Nothing is sent over the network.

---

## 11. Languages (English, French, Spanish, German, Arabic)

- Interface strings are written in English in the code and wrapped in `tr()`:
  `tr("Open PDF…")`, `tr("{n} PDF file(s) found.", n=3)`.
- `i18n.LANGUAGES` lists the languages (code → name in that language, shown in
  *View → Language*). French lives in the `FR` dictionary at the bottom of
  `convertcad/i18n.py`; Spanish, German and Arabic in `convertcad/locales/es.py`, `de.py`,
  `ar.py` (`STRINGS = {English: translation}`), imported when chosen (`i18n.table()`; the
  PyInstaller spec bundles them with `collect_submodules`). A missing translation shows
  the English text (the interface never breaks).
- `tests/test_i18n.py` fails if a `tr("…")` literal or an OCR catalogue name lacks a
  translation in any language, if a `{placeholder}` is lost, if a translation is no longer
  used (the French list is the reference), or if a guide is missing.
- **Arabic** is written right to left: `app.py` sets the application's layout direction
  (`is_rtl()`), which mirrors menus, panels and dialogs; `CadView` forces left to right so
  drawings are never mirrored.
- Lengths are formatted per language by `pdf_view.format_length()` (3,500.0 / 3 500,0 /
  3.500,0 mm). Toolbar labels that do not fit (German, Spanish) are dropped, the icon and
  tooltip remain (`MainWindow._fit_toolbar`).
- The engine (`core`) stays language-neutral: its progress messages are translated in the
  interface by `tr_progress()` (pattern based), paper names by `tr_paper()`, and the HTML
  report by passing `t=tr` to `ConversionReport.to_html()`. The `_log.txt` file is written in
  English so logs can be compared and shared.
- Long texts are Markdown files in `convertcad/resources` (`guide_<lang>`, `terms_<lang>`,
  `ocr_<lang>`); English is the fallback.
- The language applies at the next start.
- The Spanish, German and Arabic texts were written without a native-speaker review:
  corrections only change the translation, never the English key.

**Adding a language** (e.g. Italian): add `"it": "Italiano"` to `LANGUAGES`, create
`convertcad/locales/it.py` with a translation of every key of `FR`, add `guide_it.md`,
`terms_it.md`, `ocr_it.md`, and a separator rule in `format_length()` if needed; the
tests then check it automatically. For a right-to-left language add its code to
`RTL_LANGUAGES`.

---

## 12. Theme and icons

- `theme.TOKENS` holds every interface colour for the `dark` and `light` themes (background,
  panels, borders, text levels, accent teal, ok / warn / error, inputs…). `MARKUP` holds the
  colours drawn on the sheet (snap glyphs, measurements, calibration), readable on white
  paper and on the dark canvas.
- `theme.style_sheet(tokens)` generates the complete Qt style sheet from the tokens;
  `apply_theme(app, name)` applies palette + style sheet + fonts and re-tints the icons.
- To change the look, edit the tokens — nothing else. To add a theme, add a third entry to
  `TOKENS` and a menu action.
- Icons (`icons.py`) are SVG paths on a 24 px grid, rendered at 16–64 px and tinted with the
  current text colour, so they stay sharp at any display scaling. The application icon is
  `APP_ICON_SVG`; `scripts/make_icon.py` regenerates `assets/icon.ico` from it.

---

## 13. Testing

```bat
python -m pytest -q                       :: whole suite, 115 tests (≈ 70 s)
python -m pytest tests/test_geometry.py -q
python -m pytest -k dimension -q          :: tests whose name contains "dimension"
python -m ruff check .                    :: lint
```

- Test PDFs are **drawn by the tests** (`conftest.py`, `samples.py`): no binary fixtures,
  every case is readable in code.
- The OCR tests that run the models are skipped automatically when RapidOCR is not
  installed; the download tests use a local web server (no internet needed). The DWG
  tests are skipped when the LibreDWG
  programs are missing (Linux: `./scripts/build_libredwg.sh linux`; CI builds and caches
  them).
- `test_ui_smoke.py` runs the real window with `QT_QPA_PLATFORM=offscreen` (set
  automatically); it is skipped if Qt cannot start.
- When you fix a conversion problem, first add a tiny PDF reproducing it with
  `pdf_factory` + `stroke()` / `arrow()`, watch the test fail, then fix the code.

Reference results on sheet 1 of the sample plan (1:100): 8 dimensions, 2 leaders,
2 block definitions with 23 insertions (20 columns, 3 doors), 11 circles, 1 spline,
2 MTEXT notes, 1 `DIM_RAW` text, 115 entities on 15 layers.

Reference results on a dense A0 AutoCAD plot (the DPP site plan used during development,
not in the repository): 39 000 entities; 3 469 dashed lines rebuilt from 26 445 pieces;
21 hatch patterns from 478 lines; 80 SHX texts; 42 leaders; 80 blocks with 827 insertions;
scale "2.5:1000" read as 1:400; DWG written and verified in about 9 s.

---

## 14. Working in VS Code

1. Install Python 3.10+ and VS Code. Open the `ConvertCAD` folder; accept the recommended
   extensions (Python, Pylance, Ruff, EditorConfig…).
2. *Terminal → Run Task… → Set up the virtual environment* (or `scripts\setup_venv.bat`).
3. *Python: Select Interpreter* → `.venv`.
4. Press **F5** and pick a configuration:
   - **ConvertCAD (application)** — starts the window; breakpoints work in the interface and,
     thanks to `"subProcess": true`, in the conversion child process too;
   - **ConvertCAD with the sample plan**;
   - **CLI: convert the sample plan** / **the scanned sample** / **the PDF open in the editor**;
   - **Tests: current file**.
5. The *Testing* panel (flask icon) lists and runs every test.
6. Tasks: run the tests (`Ctrl+Shift+P → Tasks: Run Test Task`), lint, make samples,
   regenerate the icon, build the exe (`Ctrl+Shift+B`).

Conventions:

- 4 spaces, lines ≤ 100 characters, Ruff clean, double quotes.
- Every module starts with a docstring saying what it does and why; comments explain
  decisions, not syntax.
- Engine code never imports Qt; interface code never parses PDF geometry itself.
- New interface text → `tr("…")` + French translation in `i18n.py`.
- New option → follow the checklist in §17.1.
- Git: work on a branch, small commits with clear messages, pull request with the checklist
  of `.github/pull_request_template.md`.

---

## 15. Building the portable application and the installers

The step-by-step guide for every download (Windows portable and installer, Linux tar.gz,
AppImage and .deb), code signing and the release checklist is
**[PACKAGING.md](PACKAGING.md)**. This section explains what happens inside.

### 15.1 With the scripts

```bat
scripts\build_exe.bat            :: Windows folder build (recommended) + portable zip
scripts\build_exe.bat onefile    :: single-file build
scripts\build_installer.bat      :: Windows installer (Inno Setup)
./scripts/build_linux.sh         :: Linux folder build + tar.gz
./scripts/build_appimage.sh      :: AppImage
./scripts/build_deb.sh           :: .deb
```

`build_exe.bat`: install `requirements-dev.txt` → run the tests (the build stops if one
fails) → `scripts/make_icon.py` → `PyInstaller --noconfirm --clean ConvertCAD.spec` →
optional code signing → copy README, LICENSE, THIRD_PARTY_NOTICES, CHANGELOG → zip
`dist\ConvertCAD-<version>-win64-portable.zip`. `build_linux.sh` does the same on Linux and
builds LibreDWG first when `vendor/libredwg/linux-x86_64` is missing.

Build on **Windows** to get a Windows program and on **Linux** for Linux (PyInstaller does
not cross-compile). Use a clean `.venv`: anything installed in the Python used for the
build may end up in the bundle. On Linux, build on the oldest distribution you support.

### 15.2 What `ConvertCAD.spec` does

- **Entry points**: `main.py` → `ConvertCAD.exe` (windowed), `convertcad_cli.py` →
  `ConvertCAD-cli.exe` (console), both in the same folder sharing `_internal\`.
- **Data**: `convertcad/resources`, ezdxf's data files, RapidOCR's settings and its
  built-in PP-OCR model, the LibreDWG programs of the build platform (`_internal/libredwg/`,
  with `COPYING`, `README.md`, `SOURCE.txt`), and — offline build only — the OCR models
  placed in `vendor/ocr_models` (`_internal/ocr_models/`). A warning is printed when
  LibreDWG is missing.
- **Hidden imports**: ezdxf drawing add-on modules, RapidOCR's modules (ONNX Runtime back-end
  only), `onnxruntime`, `bidi`, `certifi` (HTTPS certificates for the model downloads),
  `PySide6.QtSvg`.
- **Excludes**: modules never used but sometimes imported optionally by libraries
  (tkinter, matplotlib, pandas, scipy, torch, Qt WebEngine/Quick/Qml…), the other OCR
  back-ends (paddle, openvino, tensorrt, MNN), the optional HTTPS add-ons of requests
  (cryptography, pyOpenSSL), the optional add-ons that PyMuPDF 2.x installs
  (`pymupdf.layout`, `pymupdf4llm`, networkx — also blocked at run time in
  `core/compat.py`), plus files never needed here: Qt's software OpenGL
  (`opengl32sw.dll`, ~20 MB) and OpenCV's video plugin (`opencv_videoio_ffmpeg*.dll`,
  ~25 MB) on Windows, Qt's GTK platform theme and the GTK libraries it pulls in on Linux.
- **Windows file properties** (version, description, copyright) generated from
  `convertcad/__init__.py`.
- **UPX disabled** — compressed executables trigger antivirus false alarms.
- `CONVERTCAD_ONEFILE=1` switches to a single-file executable (unpacks itself to a temporary
  folder at each start: slower start, but one file to carry).

### 15.3 Result

```
dist\ConvertCAD\
├── ConvertCAD.exe          the application
├── ConvertCAD-cli.exe      the command-line tool
├── _internal\              Python, Qt, MuPDF, OpenCV, NumPy, ezdxf, ONNX Runtime…
│   ├── libredwg\           dxf2dwg, dwg2dxf (DWG output), COPYING, SOURCE.txt
│   ├── rapidocr\models\    the built-in PP-OCR model (≈ 30 MB)
│   └── ocr_models\         other OCR models (offline build only)
├── README.md, LICENSE, THIRD_PARTY_NOTICES.md, CHANGELOG.md
```

The folder is large (Qt, OpenCV, MuPDF and ONNX Runtime are the largest parts): count
about 450–550 MB unpacked depending on the platform, and roughly 40 % of that for the
zip / AppImage / installer. An empty file `ConvertCAD.portable` next to `ConvertCAD.exe`
keeps the settings in `settings\` and the downloaded OCR models in `ocr_models\` beside
the program (USB stick use); the installer never installs that file.

### 15.4 Antivirus and SmartScreen

Unsigned PyInstaller programs can be flagged by SmartScreen ("unknown publisher") or,
rarely, by an antivirus. Remedies: distribute the folder build (fewer false alarms than
one-file), keep UPX off, sign the executables (`scripts\sign_windows.bat`, used by both
build scripts when `CONVERTCAD_SIGN_PFX` or `CONVERTCAD_SIGN_THUMBPRINT` is set; see
PACKAGING.md for where to get a certificate), or run from source.

### 15.5 Build troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError` when the exe starts | a lazily imported module: add it to `hiddenimports` in the spec |
| Help pages empty | `convertcad/resources` not bundled: check `datas` in the spec |
| The exe opens a second window when converting | `multiprocessing.freeze_support()` missing at the top of `main()` |
| Bundle much larger than expected | build from a clean `.venv`; add the unwanted package to `excludes` |
| "DWG output unavailable" in the built program | the spec printed "LibreDWG not found": `vendor/libredwg/win64` missing (Windows) or not built (`./scripts/build_libredwg.sh linux`) |
| OCR downloads fail in the built program only (certificate error) | `certifi` missing from the bundle: keep it in `hiddenimports` |
| `Failed to expand shell folder constant "autopf"` when testing the installer under Wine | Wine lacks the per-user Program Files folder; test with `/ALLUSERS` (real Windows is fine) |

---

## 16. Continuous integration and releases

- **`tests.yml`** — on every push to `main` and every pull request: Windows and Ubuntu ×
  Python 3.10 / 3.12 / 3.13; installs the Qt runtime libraries and the build tools on
  Linux; builds LibreDWG once and caches it (Windows uses the programs in
  the repository); runs `ruff check .` and `pytest` (DWG tests included).
- **`build.yml`** — on a tag `v*` or manually. *Windows job*: tests, PyInstaller build,
  smoke test of the built CLI (PDF → DWG, `AC1015` checked; the sample scan read by the
  built-in OCR model), optional code signing (secrets `SIGN_PFX_BASE64`,
  `SIGN_PFX_PASSWORD`), portable zip, installer with Inno Setup (Chocolatey). *Linux job*
  (Ubuntu 22.04): LibreDWG (cached), `build_linux.sh` (tests included), AppImage, .deb,
  smoke test (AppImage → DWG, OCR), and — for information only — an OCR model download from
  the built program. The five downloads are uploaded as workflow artifacts. *Release job*
  (on a tag, or *Run workflow* with **Publish the release** ticked): once both builds have
  succeeded, creates the release `v<APP_VERSION>` (tag included) with the five files and the
  CHANGELOG section of the version as notes — one job, so two jobs never create two
  releases.
- **`pages.yml`** — when `site/` changes on `main`, or manually: publishes the website
  (`site/index.html`, images in `site/img/`) on GitHub Pages,
  https://abdelhaouari-ae.github.io/ConvertCAD/. The page asks GitHub for the newest
  program release when it opens (the OCR models release is skipped, as in the update
  check) and fills the five download buttons and their sizes; offline, they lead to the
  releases page. One-time setting: *Settings → Pages → Source: GitHub Actions*.
- **`ocr-models.yml`** — manual (*Run workflow*): downloads the downloadable OCR models
  from RapidOCR's repository, checks their SHA-256, test-runs each one and publishes them
  as the release `ocr-models-v1` (not marked *latest*), where the program downloads them
  from. Run it once, then after any change of `convertcad/core/ocr_catalog.py`.

**Publishing the repository on GitHub (first time)**

1. The repository `abdelhaouari-AE/ConvertCAD` exists on GitHub (keep it empty: README and
   licence are already in the folder).
2. In a terminal opened in the project folder:

   ```bat
   git init
   git add .
   git commit -m "ConvertCAD 1.0.0"
   git branch -M main
   git remote add origin https://github.com/abdelhaouari-AE/ConvertCAD.git
   git push -u origin main
   ```

3. The *tests* workflow starts automatically (Actions tab).
4. Push the first tag to build and publish the downloads:
   `git tag v1.0.0 && git push origin v1.0.0`.

**Releasing a new version**

1. Update `APP_VERSION` in `convertcad/__init__.py` (the only place).
2. Add the version to `CHANGELOG.md`.
3. Commit and push to `main`.
4. *Actions → build → Run workflow*, tick **Publish the release** (or push the tag
   `v<version>`): the five downloads are built and published as the release, with the
   changelog section as notes. The website offers the new version at once.

Version numbers follow *major.minor.patch*: patch = fixes, minor = new features compatible
with existing settings, major = big changes (interface, file formats, dependencies).

---

## 17. Extending ConvertCAD — recipes

### 17.1 Add a new conversion option (checklist)

1. `core/options.py`: add the field to `Options` with a default and a comment (and a check
   in `from_dict()` when it has a fixed set of values); use it in the engine; add it to
   `Options.describe()` so it appears in the log.
2. `ui/options_panel.py`: add the control in the right section (with a tooltip); map it in
   `options()` and `set_options()`; update `_update_enabled()` if it depends on another option.
3. `cli.py`: add an argument and map it in `options_from_args()` (if useful from scripts).
4. `i18n.py`: French translations of the label and the tooltip.
5. `core/presets.py`: set it in the presets where it matters.
6. Tests: an engine test proving the effect, plus the CLI mapping if added.
7. `resources/guide_*.md`, this guide §8, `CHANGELOG.md`.

### 17.2 Add licence management

Replace the body of `core/licensing.py` only: `check_license()` returns `(False, message)`
to block a conversion (the message appears in the report and the interface);
`license_summary()` is shown in the About box. Keep the signatures. If a licence key must be
entered, add a small dialog in `ui/dialogs.py` and store the key in `Settings`. Note that the
AGPL licence (§20) lets anyone remove such a check from the source; closed-source
distribution requires a commercial PyMuPDF licence.

### 17.3 Add a standard texture pattern

Add its name (as in ezdxf's `ezdxf.tools.pattern.ISO_PATTERN`, a copy of AutoCAD's
`acadiso.pat`) to `textures.TEXTURES`; if it contains dots, add its share of dots to
`DOT_SHARE`; if it looks random (no short repeat), add it to `RANDOM_LOOKING`. Then add a
case to `tests/test_textures.py` (`_draw` draws any standard pattern into a PDF the way
AutoCAD plots it). Patterns that are geometrically identical up to the scale (BRICK and
AR-B816) are found as the first one listed.

### 17.4 Add another kind of dimension (ordinate, jogged radius…)

Add a recogniser in `core/annotations.py` that returns a new dataclass (like
`RadialDimension` or `AngularDimension`), mark the consumed primitives, call it in
`reconstruct()` before the linear dimensions if its arrows could pass for a linear
dimension, then emit it in `DxfWriter.write_annotations()` with ezdxf (sizes from
`_dim_override()`, `_undo_from()` on failure). Follow the safe rule: only when the arrow,
the geometry and the text agree; otherwise leave the primitives alone. Check the DWG round
trip (`dwg.py` may have to adapt the DXF, as for the 3-point angular dimension).

### 17.5 Add a preset

Add an entry to `BUILTIN_PRESETS` in `core/presets.py` (label + only the options it changes)
and its French label in `i18n.py`. It appears in the interface and in `--preset`.

### 17.6 Add a DXF feature or entity type

All DXF writing is in `core/dxf_writer.py`: add a `write_*` method, call it from
`pipeline._convert_dxf()` in the per-page sequence, count it in `WriteStats`
(`core/stats.py`) and `RESULT_ROWS` (`core/report.py`), and provide an R12 fallback when
the entity does not exist in R12. Check that DWG output keeps it: an entity that DWG 2000
cannot hold must be written differently for `Options.writer_dxf_version() == "R2000"`, and
`tests/test_dwg.py` shows how to verify a round trip.

### 17.7 Update the bundled LibreDWG

1. Put the new upstream tarball in `vendor/libredwg/`, update `VERSION` and `SHA256` in
   `scripts/build_libredwg.sh`.
2. Check each patch of `vendor/libredwg/patches/` (drop the ones fixed upstream).
3. `./scripts/build_libredwg.sh linux` then `windows`; run `pytest tests/test_dwg.py`.
4. Commit the new `win64/` programs; the CI cache key changes with the patches and the
   script, so Linux builds rebuild automatically.

---

## 18. Performance notes

| Case | Result (development machine) |
|---|---|
| Start-up (window shown) | ≈ 0.35–0.5 s (was ≈ 0.8–1 s) |
| Sample plan (A3, 2 sheets) | ≈ 0.1 s engine time, ≈ 2–3 s in the interface (process start + preview) |
| A0 stress sheet, 35 000 primitives | ≈ 5 s |
| Dense A0 AutoCAD plot (DPP, 39 000 entities written) | ≈ 18 s to DXF, + ≈ 9 s to DWG (LibreDWG + read-back) |
| DXF preview of that plot | ≈ 650 scene items, repaint 20–30 ms |
| Scanned A3 at 300 dpi with OCR | ≈ 6–8 s with the command line (≈ 1 270 lines, 8 circles, 30 OCR texts) |
| Scanned A1 at 200 dpi, 260 labels (2 CPU cores) | OCR ≈ 20 s (80 % of the labels; 1.0: 31–44 %); maximum accuracy ≈ 5 min (83 %); tracing ≈ 9–13 s (1.1.0: ≈ 4–5 min, circle search) |

Where the speed comes from:

- **Start-up.** `convertcad.core` loads its names lazily (PEP 562); the interface modules
  import PyMuPDF, ezdxf, NumPy and the post-processing code only where they are used; the
  options panel is built from `core/options.py` and `constants.py` (standard library only).
  300 ms after the window shows, `app._warm_up()` imports the heavy libraries in a
  background thread, so the first *Open* and *Convert* do not wait either. Measure with
  `CONVERTCAD_STARTUP_PROBE=1 python main.py`.
- **Engine.** Spatial grid indexes in every neighbourhood search (annotations, blocks,
  patterns, snap, chaining), PyMuPDF's C-level path listing (`get_cdrawings`) for
  inspection, conversion in a separate process.
- **Viewers.** Tile rendering of the PDF; DXF preview rendered and merged in a thread
  (`dxf_view.merge_recording`), cosmetic pens.
- **DWG.** LibreDWG's DXF reader was quadratic (patch 02): 243 s → 9 s on the DPP plot.

---

## 19. Known limitations and roadmap

- **DWG**: written in the AutoCAD 2000 format only (what LibreDWG writes); every AutoCAD
  since 2000 and every current CAD program opens it, and saving it again from AutoCAD gives
  the latest format. Entities that DWG 2000 cannot hold are written in their AutoCAD 2000
  form (classic LEADER + MTEXT instead of MULTILEADER, ACI colours).
- **OCR**: one script besides Latin per drawing (Latin + Arabic, Latin + Cyrillic…);
  vertical text read top-to-bottom may come out with the wrong rotation; the downloaded
  models come from the GitHub release only when the repository is public (otherwise from
  RapidOCR's repository).
- Blocks: copies at any angle and mirrored are matched; copies at another size are
  different symbols.
- Dimensions: linear (aligned/rotated), radius, diameter, angle (3 points) and arc length;
  ordinate, jogged-radius and 2-line angular dimensions remain geometry + text. Arc length
  dimensions are written as ARC_DIMENSION from DXF 2007 only (their drawing otherwise).
- Scanned drawings: tracing is approximate by nature (lines, circles and arcs; no
  splines); always compare with the locked scan layer.
- Hatch patterns are rebuilt when they are made of straight parallel lines (single
  direction or crossing grids) or come from the standard textures of `textures.TEXTURES`;
  custom patterns, curved patterns and several patterns touching each other stay as their
  geometry. Sand and concrete are accepted on statistics (estimated scale and position).
- Interface translations (Spanish, German, Arabic) have not been reviewed by native
  speakers.
- One scale per sheet (viewports at different scales on one sheet: convert each area with
  its own calibration, using *Select area*).
- No macOS build (the code runs on macOS from source, untested).

Ideas for next versions: drawing content in model space with the title block in a paper
space layout, DWG in newer formats when LibreDWG supports them, viewport-aware scales,
macOS build, licence management (hook ready).

---

## 20. Licences

ConvertCAD is © 2026 abdelhaouari and released under the **GNU AGPL v3.0** (see
`LICENSE`), because it links PyMuPDF, which is licensed under AGPL-3.0 (or a commercial
licence from Artifex). In practice:

- anyone may use, study, modify and redistribute ConvertCAD, including commercially, as long
  as the source code (with modifications) is made available under the same licence;
- a **closed-source or proprietary** distribution of ConvertCAD (for example with licence
  keys that users cannot remove) requires a **commercial PyMuPDF licence** — or replacing
  PyMuPDF by a library with a permissive licence;
- Qt (PySide6) is LGPL-3.0: the folder build keeps the Qt libraries as separate files that a
  user can replace, which is what the LGPL requires;
- GNU LibreDWG is GPL-3.0-or-later and runs as a separate program; its complete source,
  the ConvertCAD patches and the build script are in `vendor/libredwg/` and
  `scripts/build_libredwg.sh`, and `SOURCE.txt` next to the bundled programs says where to
  find them. The ODA File Converter is not used (its licence forbids bundling it).

All third-party licences: [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

---

## 21. Version history

| Version | Date | Highlights |
|---|---|---|
| 1.2.0 | 2026-10-30 | Radius, diameter, angle and arc length dimensions; texture hatches (dots, sand, concrete, gravel, earth, brick, insulation) rebuilt as standard patterns; repeated symbols at any angle; arcs traced on scanned drawings; selection in the result preview; interface in Spanish, German and Arabic (right to left); optional update check (off by default) |
| 1.1.2 | 2026-10-30 | Select area: the page background is no longer written as a hatch of the area's size |
| 1.1.1 | 2026-10-29 | Circle search of scanned pages about 30 times faster on large sheets (two radius bands, reduced copy for large circles, vectorised checks) |
| 1.1.0 | 2026-10-29 | OCR: one built-in PP-OCR model (English, French, Latin-script languages), other scripts and maximum accuracy downloaded from the program (*OCR languages and models…*, `--get-ocr-model`), mixed-script drawings, offline installation from files; Tesseract and the PaddleOCR library removed; smaller downloads |
| 1.0.0 | 2026-10-29 | First public release: Qt 6 interface (dark/light, EN/FR, review before saving), vector engine (arcs, splines, polylines, dimensions, leaders, blocks with rotations, dashed lines and hatch patterns rebuilt, SHX texts), scanned drawings with three OCR engines, selected-area conversion, overlay check, native DWG output, command line, Windows portable + installer, Linux tar.gz + AppImage + .deb |

The program was developed privately before this release (internal versions 1.x–3.x);
version numbers restart at 1.0.0 for the public repository. Details:
[`CHANGELOG.md`](../CHANGELOG.md).
