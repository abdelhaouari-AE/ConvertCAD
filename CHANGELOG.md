# Changelog

All notable changes to ConvertCAD. Versions follow *major.minor.patch*.

## [1.1.2] — 2026-10-30

### Fixed
- **Select area**: a coloured page background was cut to the selected area and written as a
  hatch of the area's size, which hid the drawing in CAD and covered the overlay check. The
  page background is now recognised when the page is read, before the cut, and left out as
  on a whole-sheet conversion (a white page background is no longer taken for a text mask
  either).

## [1.1.1] — 2026-10-29

### Fixed
- **Large scanned sheets are traced about 30 times faster**: the circle search took 4–5
  minutes on an A1 sheet (200 dpi); it now takes seconds. Small circles are searched at
  full resolution, large ones on a reduced copy and then placed exactly at full
  resolution; the speckles of poor scans are smoothed out first, and a circle is kept only
  when the ink really follows its perimeter. The same circles are found (sample scan: the
  same 13; A1 test sheet with 40 circles: 35 found in 7–8 s, clean or poor scan — 35
  before, in about 4 min).

## [1.1.0] — 2026-10-29

OCR rebuilt around one engine: PaddleOCR's PP-OCR models run by RapidOCR, with one model
built in and the others downloaded from the program when needed.

### Added
- **OCR languages and models…** (*Settings → Scanned pages*, *Tools* menu): download
  Arabic, Cyrillic, Greek, Korean, Devanagari, Thai, Tamil, Telugu and the maximum
  accuracy models from a drop-down list, with a progress bar and *Cancel*; remove them;
  **Install from file…** for computers without internet (files recognised by their
  checksum). Every file is checked (SHA-256) before it is kept.
- Models stored per user (`%LOCALAPPDATA%\ConvertCAD\ocr_models`,
  `~/.local/share/convertcad/ocr_models`), next to the program in portable mode, or in
  `CONVERTCAD_OCR_MODELS`; the Windows uninstaller removes them, updates keep them.
- **Mixed-script drawings**: *English, French… + Arabic* (or another script) reads both,
  each line keeping the reading of its own script.
- *OCR accuracy*: Standard (built-in model) or Maximum (larger models).
- Command line: `--ocr-lang latin|<script>|latin+<script>`, `--ocr-quality
  standard|maximum`, `--get-ocr-model ID…`; `--list-ocr` lists the models.
- Workflow *OCR models release* publishes the downloadable models (release
  `ocr-models-v1`); `scripts/get_ocr_models.py` reworked for maintainers.

### Changed
- One built-in OCR model (PP-OCRv6 small, about 30 MB): English, French and 45 other
  Latin-script languages, plus Chinese and Japanese. The language list shows the installed
  languages only; a missing choice stays visible, marked *(not downloaded)*, and the
  built-in model is used (the report says so).
- The downloads no longer bundle the larger OCR models and the Arabic model (smaller
  downloads); 1.0 settings are converted (`eng+fra+ara` → *English, French… + Arabic*,
  *Maximum — PaddleOCR* → *Maximum* accuracy).
- The only network connection of the program: downloading an OCR model when the user asks
  (terms of use updated).
- **Large sheets are read much better**: the OCR reads the page at 150 dpi (at least 2000
  pixels on the long side) instead of shrinking every page to 2000 pixels. On an A1 test
  sheet with 260 labels of 1.8–3.5 mm, about 80 % are read instead of 31–44 %; large
  sheets take longer.

### Fixed
- Arabic lines (and the new Thai and Devanagari models) are no longer turned upside down
  by the text-orientation classifier, which is not used with the script models any more.
- **Privacy:** ONNX Runtime (the OCR runtime) recorded usage data — program path,
  system, processor, a device identifier — and uploaded it to Microsoft (seen on Linux
  with ONNX Runtime 1.31); 1.0 switched off only its events, too late. It is now switched
  off before the library loads (`ORT_DISABLE_TELEMETRY`), so ConvertCAD really sends
  nothing.

### Removed
- The Tesseract OCR engine (and pytesseract), the optional PaddleOCR library
  (`requirements-paddle.txt`), the *OCR engine* setting and *Also read vertical text*
  (vertical text is always read).

## [1.0.0] — 2026-10-29

First public release. ConvertCAD converts 2D PDF drawings — vector exports from CAD
software or scans — into editable **DXF and DWG** files built with real CAD entities.

### Conversion
- Geometry: Bezier curves rebuilt as true ARC / CIRCLE or one exact SPLINE, touching
  segments joined into LWPOLYLINEs, duplicates removed, page rotation handled.
- **Dashed lines rebuilt**: dashes that CAD plotters write as separate pieces become one
  line with a linetype measured on the PDF (DASHED, CENTER, DASHDOT, PHANTOM, DOT, DIVIDE).
- **Hatch patterns rebuilt**: hundreds of parallel lines become one pattern HATCH with its
  angle and spacing (gratings too); white masks under texts become holes. Solid fills
  become SOLID hatches.
- Real **DIMENSION** entities from arrows or oblique ticks + line + value (the PDF value is
  kept); unmatched measurement texts go to the review layer `DIM_RAW`.
- **Leaders** rebuilt as MULTILEADER (classic LEADER for old DXF versions), with
  multi-line notes, arrows at the line end or at the arrow base, notes on or under the
  landing; stair "UP / DN" arrows and titles are not taken as leaders.
- **Blocks**: repeated symbols become one BLOCK and INSERTs — including copies rotated by
  90°/180°/270° and mirrored copies.
- Text: TEXT and MTEXT paragraphs; **AutoCAD SHX text** recovered as real text placed on its
  letters (the strokes kept on a hidden layer); TrueType text drawn as outlines replaced by
  the real text.
- Layers from the PDF (OCG) or by style / colour; AutoCAD Color Index or true colour; white
  masks, white lines and page backgrounds left out; raster images placed and oriented
  exactly.
- Scale read on the sheet ("Echelle : 1/100", "SCALE 1:50", "2.5:1000" → 1:400), per-sheet
  scale for mixed sets, calibration on two points.
- **Convert only a selected area** of the sheet.
- Scanned drawings: line and circle tracing and OCR with **three engines** — *Fast —
  Tesseract*, *Accurate — RapidOCR* (PaddleOCR's PP-OCR models, default), *Maximum —
  PaddleOCR* (larger PP-OCR models); English, French, Arabic.

### Output
- DXF R12 → R2018, one file or one file per sheet, conversion log next to the drawing.
- **Native DWG** (AutoCAD 2000 format) written by the bundled GNU LibreDWG converter and
  read back to check every entity and block reference. No separate installation.

### Interface
- Qt 6 interface, dark and light themes, English and French, crisp at every display
  scaling; four-step workflow *Open → Check the scale → Convert → Review and save*.
- Source PDF viewer (sharp at any zoom) with Measure, Calibrate and Select-area tools and
  object snap END / MID / INT / CEN.
- Review before saving: DXF preview as CAD software reads it (fast on 40 000-entity sheets),
  **overlay check** with the PDF underneath, layer table (keep / hide, rename, recolour),
  detailed report.
- Settings panel with every option, built-in and user presets; folder batch; recent files;
  drag & drop; keyboard shortcuts.
- Fast start: the window opens in about half a second, libraries load in the background.

### Tools and distribution
- Command line (`ConvertCAD-cli`, `python -m convertcad --cli`): every option, DWG output,
  area, OCR engine, presets, batch, JSON report, exit codes.
- Windows: portable zip and installer (Inno Setup, no admin rights needed); Linux:
  tar.gz, AppImage and .deb. Every download includes the DWG converter and the OCR engines
  and models (Windows: Tesseract too).
- 115 automated tests; GitHub Actions for tests on Windows and Linux and for building and
  publishing the downloads; optional code signing.
