# ConvertCAD user guide

ConvertCAD turns 2D PDF drawings into **editable DXF or DWG files built with real CAD entities**: lines, polylines, arcs, circles, splines, hatches, text and paragraphs, true dimensions, leaders, layers and blocks — not exploded line spaghetti. Everything runs on your computer.

## The four steps

1. **Open a drawing** — *Open PDF…* (Ctrl+O), drag a PDF onto the window, or try the sample plan. Each sheet appears on the left with a badge: **Vector** (ideal), **Scan** (will be traced and read with OCR) or **Empty**. Untick the sheets you do not want to convert; the selection menu in the *Sheets* header selects all, none, only vector or only scanned sheets.
2. **Check the scale** — choose the drawing scale in *Settings > Scale, units and area* (ConvertCAD reads it from the title block when it can). For an exact result, use **Calibrate** (C): click two points whose real distance you know — for example two grid axes — and type the distance. Use **Measure** (M) to verify any distance before converting. To convert only part of the sheet, use **Select area** (A) and drag a rectangle; *Whole sheet* removes it.
3. **Convert** (Ctrl+Enter) — runs in the background; you can keep zooming or cancel at any time.
4. **Review and save** — the *DXF result* tab shows the converted drawing exactly as CAD software will read it. **Overlay PDF** (O) lays the PDF underneath, with an opacity slider: any difference shows at once. Click an entity of the result to select it: it is highlighted, the status bar shows its type, layer and size, and its layer is selected in *Layers*. In *Layers*, untick layers you do not want, rename them (double-click) or recolour them (click the swatch); the ↺ button undoes every layer change. The *Report* lists everything that was created, with warnings. Then **Save DXF…** (Ctrl+S) — or **Save DWG…**: choose the DWG type in the save dialog, or set *Settings > Output > File format* to DWG before converting.

## Navigating the drawing

| Action | How |
|---|---|
| Zoom at the cursor | Mouse wheel |
| Pan | Middle-button drag, Space + drag, or left drag with the Pan tool |
| Fit the sheet | F |
| Collapse / open a side panel | Click its bar on the window edge; Ctrl+0 collapses both (like AutoCAD's *Clean screen*) |
| Next / previous sheet | Page Down / Page Up |
| Cancel a tool | Escape (right-click cancels the first point) |

The sheet stays sharp at any zoom: the visible area is re-rendered at screen resolution.

## Object snap

When measuring or calibrating, clicks jump to the exact point of the drawing, like AutoCAD's OSNAP. The status bar toggles each mode:

- **END** — endpoints and corners (square marker)
- **MID** — midpoints of segments (triangle)
- **INT** — intersections (cross)
- **CEN** — centres of circles and arcs (circle)

F3 switches snapping on or off.

## What the conversion produces

| In the PDF | In the DXF |
|---|---|
| Circular curves | True **ARC** and **CIRCLE** entities |
| Curves in several pieces | One exact **SPLINE** |
| Touching segments | One **LWPOLYLINE** (closed when it loops) |
| Dash patterns, or dashes drawn as separate pieces | One line with a linetype **CENTER**, **DASHED**, **DASHDOT**, **PHANTOM**… measured on the PDF |
| Filled areas | Solid **HATCH** on layer HATCH |
| Hatching drawn as many parallel lines | One pattern **HATCH** (angle and spacing of the PDF) |
| Sand, concrete, gravel, earth, brick, insulation or dots drawn as many dashes and dots | One **HATCH** with the standard pattern (AR-SAND, AR-CONC, GRAVEL, EARTH, BRICK, INSUL, DOTS…) at the scale and angle measured on the PDF |
| Text | **TEXT** in the PDF's font (Arial, Times New Roman, Courier New, Calibri…, bold and italic), size and length; stacked lines become one **MTEXT** paragraph, left-aligned, centred or right-aligned like the PDF |
| AutoCAD SHX text drawn as strokes | Real **TEXT** on layer TEXT_SHX (the strokes are kept on the hidden layer TEXT_SHX_STROKES) |
| Arrow + line + arrow + value | Real **DIMENSION** (layer DIM) — the value keeps the PDF text |
| Oblique ticks + line + value | Real **DIMENSION** with architectural ticks |
| Arrow on a circle or an arc + "R…" / "Ø…" value | Real **RADIUS** / **DIAMETER** dimension |
| Two arrows on an arc + an angle ("45°") or an arc length | Real **ANGULAR** / **ARC LENGTH** dimension — only when the value agrees with the drawn arc |
| Arrow + line + note | **LEADER** / multileader (layer ANNOT_LEADER) |
| Identical repeated symbols, even turned by any angle or mirrored | One **BLOCK** + one INSERT per occurrence |
| Scanned sheets | **LINE**, **CIRCLE** and **ARC** on layer TRACE_LINES, text read by OCR |
| Embedded images, scans | Image on the locked layer IMG_RASTER |

Measurement texts that matched no dimension are put on layer **DIM_RAW** (red) so you can review them. Nothing is invented: a pattern or a dimension is rebuilt only when it reproduces the PDF; otherwise its pieces are kept as they are. The arc length dimension is written as a true ARC_DIMENSION from DXF 2007; for older versions and DWG it is kept as its drawing on layer DIM.

## Settings explained

**Scale, units and area** — drawing scale (1:N, or 1/4" = 1'-0" and 1" = 20' in inches and feet) and DXF unit (mm, cm, m, inches, feet); *Select area… / Whole sheet* (only the area is converted, in the sheet's own coordinates; the area applies to every converted sheet). *Read the scale written on each sheet* is for sets whose sheets have different scales (plan at 1:100, details at 1:20): each sheet uses the scale of its title block, and the scale above is used when a sheet shows none or several; the report says which scale each sheet received. Calibration overrides both; the panel shows the equivalent scale ("about 1:100.2") as a sanity check.

**Geometry** — rebuild arcs and circles; join segments into polylines; join curves into single splines; *curve precision* (Fine / Normal / Loose) sets how strictly a curve must match a circle; solid fills as hatches; *rebuild hatch patterns* (parallel lines → pattern HATCH; sand, concrete, gravel, earth, brick, insulation, dots → the standard pattern; sand and concrete look random, so their scale and position are estimated and the report says so); *rebuild dashed lines* (separate dashes → one line with a linetype); ignore white masks, white lines and page backgrounds (they would hide the drawing in CAD).

**Text** — export text; group stacked lines into MTEXT paragraphs; *text height ratio* (capital height ÷ PDF font size) for fonts ConvertCAD does not recognise — recognised fonts keep their own size; changing it applies the ratio to every text; *recover text drawn as strokes or outlines*: AutoCAD SHX text comes back as real text (layer TEXT_SHX) from the hidden comments AutoCAD adds to its PDFs, and TrueType text drawn as filled outlines is replaced by its real text.

**Dimensions and leaders** — rebuild dimensions with arrows (linear, radius, diameter, angle, arc length) and/or tick marks; rebuild leaders.

**Layers and blocks** — keep the PDF's own layers when it has them; *layer naming* when it has none: colour + lineweight + linetype (e.g. GEO_BLACK_050_CENTER), colour only, or a single layer; recognise linetypes; *colours*: AutoCAD Color Index (works with CTB plot styles) or true colour (exact RGB); detect repeated symbols as blocks, with a minimum number of occurrences, and *also match rotated and mirrored copies* (any angle).

**Scanned pages** — trace lines, circles and arcs; read text with OCR (PP-OCR models, on this computer); *OCR languages*: English, French… (Latin script, built in), another script (Arabic, Cyrillic, Greek…) or both for mixed drawings — only the installed ones are listed; *OCR accuracy*: Standard (built-in model) or Maximum (larger models, slower); **OCR languages and models…** downloads the other languages and the maximum accuracy models, or installs them from files on a computer without internet (see *Help > OCR guide*); scan resolution (200–600 dpi); use the PDF's own text layer when the scan is already searchable; keep raster images on a locked layer.

**Output** — *file format*: DXF, or DWG (AutoCAD 2000 format: opens in every AutoCAD since 2000 and every current CAD program; written by the included GNU LibreDWG converter and checked after writing); DXF version (R2018 for current software, R12 for old CNC machines); with several sheets, one DXF with sheets side by side or one DXF per sheet; write a conversion log next to the DXF; open the folder after saving.

**Presets** — ready-made settings: Recommended, Architectural plans, Structural / formwork plans, Scanned archive drawings, Geometry only, CNC / laser. *Save as preset…* keeps your own combinations.

## Interface language

*View > Language*: English, Français, Español, Deutsch or العربية (Arabic, written right to left: the whole window is mirrored, the drawings are not). The change applies at the next start. The OCR languages are chosen separately (*Settings > Scanned pages*).

## Updates

ConvertCAD never connects to the internet by itself. *Help > Check for updates…* asks GitHub, once, whether a newer version exists; *Help > Check for updates at startup* does it at each start (off by default). Nothing is sent and nothing is installed: when a newer version exists, ConvertCAD shows its number and can open its release page.

## Converting a whole folder

*Convert a folder…* (Ctrl+B) converts every PDF of a folder (optionally with sub-folders) with the current settings. Each file gets its DXF (or DWG) and its log in the output folder. Calibration does not apply in this mode: by default each sheet uses the scale written in its title block, otherwise the drawing scale of the settings — check it in each log.

The same conversions can be scripted with the console program *ConvertCAD-cli.exe* (next to ConvertCAD.exe) — type `ConvertCAD-cli --help` in a command prompt.

## Engineering checklist after every conversion

1. Measure a known distance in CAD to confirm the scale.
2. Show only layer DIM and spot-check values against the PDF.
3. Review layer DIM_RAW.
4. Read the warnings of the report.

## Troubleshooting

- **Text arrives as small strokes** — the PDF was produced with SHX fonts without the hidden comments (not an AutoCAD PDF, or exported without them): the strokes stay geometry. For AutoCAD PDFs, keep *Recover text drawn as strokes or outlines* on.
- **The drawing is hidden by a white area in CAD** — keep *Ignore white masks, white lines and page backgrounds* on.
- **OCR is poor** — check the *OCR languages* (a Cyrillic or Arabic drawing needs its script: *OCR languages and models…*); for poor scans or small text choose *OCR accuracy: Maximum* or a higher scan resolution; see *Help > OCR guide*.
- **An OCR download fails** — check the internet connection or the company proxy; on a computer without internet use *Install from file…* (see *Help > OCR guide*).
- **The DWG could not be written** — the report says why, and the drawing is saved as DXF instead; send the PDF with the log if it happens again.
- **Too many small layers** — choose *Colour only* or *Single geometry layer*, or untick layers before saving.
- **A repeated symbol was not turned into a block** — its copies differ (size, a missing piece) or it appears fewer times than *Minimum occurrences*.
- **A hatch stayed as many small lines** — it matched no standard pattern closely enough (custom pattern, several patterns touching each other): its pieces are kept, nothing is invented.
- **A conversion is slow** — very large scans: lower the scan resolution.

ConvertCAD {APP_VERSION} — © {APP_YEAR} {APP_AUTHOR}
