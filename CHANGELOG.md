# Changelog

All notable changes to ConvertCAD. Versions follow *major.minor.patch*.

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
