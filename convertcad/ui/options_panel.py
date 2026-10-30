"""
options_panel.py — every conversion option, grouped and explained.

Groups (collapsible): Scale, units and area · Geometry · Text · Dimensions
and leaders · Layers and blocks · Scanned pages · Output. A preset selector at
the top applies ready-made option sets; users can save their own.
Every control has a plain-language tooltip.

The panel converts to and from core.pipeline.Options, so the engine and
the interface always agree on what each option means.
"""

import re
from typing import Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QGridLayout, QHBoxLayout, QInputDialog, QMenu,
                               QPushButton, QScrollArea, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..core.constants import (DXF_VERSIONS, OCR_QUALITIES, PAPER_SCALES,
                              RASTER_DPI_CHOICES, UNITS)
from ..core.ocr_catalog import BY_ID, language_set
from ..core.options import Options
from ..core.units import effective_denominator
from ..core.presets import (BUILTIN_PRESETS, apply_preset,
                            preset_from_options)
from ..i18n import tr
from . import theme
from .icons import icon
from .widgets import CollapsibleSection, label, restyle


def _fmt_den(den: float) -> str:
    return f"{den:.0f}" if abs(den - round(den)) < 0.05 else f"{den:.1f}"


class OptionsPanel(QScrollArea):
    changed = Signal()
    calibrate_requested = Signal()
    calibration_reset = Signal()
    area_requested = Signal()
    area_cleared = Signal()
    preset_message = Signal(str)
    ocr_models_requested = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._loading = False
        self._snapshot: Dict = {}
        self._cal_units_per_pt = 0.0
        self._clip_rect = None                 # [x0, y0, x1, y1] page pt
        self._area_text = ""
        body = QWidget()
        body.setObjectName("Panel")
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(10, 8, 10, 12)
        root.setSpacing(0)
        root.addLayout(self._preset_row())
        self.notice = label("", "notice", wrap=True)
        self.notice.hide()
        root.addSpacing(6)
        root.addWidget(self.notice)
        root.addSpacing(6)
        self.sections = {}
        for key, title, builder, open_ in (
                ("scale", tr("Scale, units and area"), self._scale_section,
                 True),
                ("geometry", tr("Geometry"), self._geometry_section, False),
                ("text", tr("Text"), self._text_section, False),
                ("dims", tr("Dimensions and leaders"), self._dims_section,
                 False),
                ("layers", tr("Layers and blocks"), self._layers_section,
                 False),
                ("scan", tr("Scanned pages"), self._scan_section, False),
                ("output", tr("Output"), self._output_section, True)):
            sec = CollapsibleSection(title, open_)
            builder(sec)
            self.sections[key] = sec
            root.addWidget(sec)
        root.addStretch(1)
        self.set_options(Options.from_dict(settings.options))
        self._snapshot = self.options().to_dict()
        self._update_modified()

    # ---- small builders -------------------------------------------------------------
    def _check(self, text: str, tip: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setToolTip(tip)
        cb.toggled.connect(self._on_change)
        return cb

    def _combo(self, items, tip: str, editable: bool = False) -> QComboBox:
        c = QComboBox()
        for text, data in items:
            c.addItem(text, data)
        c.setToolTip(tip)
        c.setEditable(editable)
        c.currentIndexChanged.connect(self._on_change)
        c.setMinimumWidth(130)
        return c

    def _row(self, sec: CollapsibleSection, text: str, w: QWidget,
             stacked: bool = False) -> None:
        """Label + field. ``stacked`` puts the field under its label at full
        width: used for combos with long choices, so no text is ever clipped
        in this narrow panel, whatever the language."""
        lb = label(text, "muted")
        lb.setToolTip(w.toolTip())
        if stacked:
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(3)
            box.addWidget(lb)
            box.addWidget(w)
            sec.add_layout(box)
            return
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.addWidget(lb, 0, 0)
        grid.addWidget(w, 0, 1, Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(0, 1)
        sec.add_layout(grid)

    # ---- preset row --------------------------------------------------------------------
    def _preset_row(self):
        lay = QVBoxLayout()
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(tr("Preset"), "muted"))
        self.modified = label(tr("Modified"), "warn")
        self.modified.hide()
        top.addStretch(1)
        top.addWidget(self.modified)
        lay.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.preset = QComboBox()
        self.preset.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(14)
        self._fill_presets()
        self.preset.activated.connect(self._on_preset)
        row.addWidget(self.preset, 1)
        more = QToolButton()
        more.setIcon(icon("settings", theme.tok("text_muted")))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Save as preset…"), self._save_preset)
        self.act_delete = menu.addAction(tr("Delete preset"),
                                         self._delete_preset)
        menu.addSeparator()
        menu.addAction(tr("Reset to defaults"), self.reset_defaults)
        more.setMenu(menu)
        row.addWidget(more)
        lay.addLayout(row)
        return lay

    def _fill_presets(self, select: str = "") -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        for key, p in BUILTIN_PRESETS.items():
            self.preset.addItem(tr(p["label"]), ("builtin", key))
        if self.settings.presets:
            self.preset.insertSeparator(self.preset.count())
            for name in sorted(self.settings.presets):
                self.preset.addItem(name, ("user", name))
        if select:
            for i in range(self.preset.count()):
                if self.preset.itemData(i) and self.preset.itemData(i)[1] == select:
                    self.preset.setCurrentIndex(i)
        self.preset.blockSignals(False)

    def _on_preset(self, index: int) -> None:
        data = self.preset.itemData(index)
        if not data:
            return
        kind, key = data
        if kind == "builtin":
            opt = apply_preset(self.options(), BUILTIN_PRESETS[key]["options"])
            name = tr(BUILTIN_PRESETS[key]["label"])
        else:
            opt = apply_preset(self.options(), self.settings.presets[key],
                               builtin=False)
            name = key
        self.set_options(opt)
        self._snapshot = self.options().to_dict()
        self._update_modified()
        self.changed.emit()
        self.preset_message.emit(tr("Preset \"{name}\" applied.", name=name))

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Save as preset…"),
                                        tr("Preset name"))
        name = (name or "").strip()
        if not ok or not name:
            return
        self.settings.presets[name] = preset_from_options(self.options())
        self.settings.save()
        self._fill_presets(select=name)
        self._snapshot = self.options().to_dict()
        self._update_modified()
        self.preset_message.emit(tr("Preset \"{name}\" saved.", name=name))

    def _delete_preset(self) -> None:
        data = self.preset.currentData()
        if data and data[0] == "user":
            self.settings.presets.pop(data[1], None)
            self.settings.save()
            self._fill_presets()

    def reset_defaults(self) -> None:
        cur = self.options()
        opt = Options(scale_denominator=cur.scale_denominator, units=cur.units,
                      clip_rect=cur.clip_rect)
        self.set_options(opt)
        self.preset.setCurrentIndex(0)
        self._snapshot = self.options().to_dict()
        self._update_modified()
        self.changed.emit()

    def _update_modified(self) -> None:
        cur = self.options().to_dict()
        diff = {k for k in cur if cur[k] != self._snapshot.get(k)} - {
            "scale_denominator", "units", "pages", "calibrated_units_per_pt",
            "auto_scale", "clip_rect"}
        self.modified.setVisible(bool(diff))
        data = self.preset.currentData()
        self.act_delete.setEnabled(bool(data and data[0] == "user"))

    # ---- sections ---------------------------------------------------------------------
    def _scale_section(self, sec: CollapsibleSection) -> None:
        self.scale = QComboBox()
        self.scale.setEditable(True)
        for n in PAPER_SCALES:
            self.scale.addItem(f"1:{n}", n)
        self.scale.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"^\s*(1\s*[:/]\s*)?\d{1,6}([.,]\d+)?\s*$")))
        self.scale.setToolTip(tr("Scale of the PDF sheet, e.g. 1:100. "
                                 "Ignored when the drawing is calibrated."))
        self.scale.currentIndexChanged.connect(self._on_change)
        self.scale.lineEdit().editingFinished.connect(self._on_change)
        self.scale.setMinimumWidth(130)
        self._row(sec, tr("Drawing scale"), self.scale)
        self.units = self._combo([(tr(UNITS[u]["label"]), u) for u in UNITS],
                                 tr("Real-world unit of the DXF coordinates."))
        self._row(sec, tr("Units"), self.units)
        self.auto_scale = sec.add(self._check(
            tr("Read the scale written on each sheet"),
            tr("For sets whose sheets have different scales: each sheet uses "
               "the scale of its title block (1:100, 1/50…). The scale above "
               "is used when a sheet shows none, or several.")))
        self.cal_label = label("", "muted", wrap=True)
        sec.add(self.cal_label)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_cal = QPushButton(icon("calibrate"), tr("Calibrate…"))
        self.btn_cal.setToolTip(tr("Click two points with a known distance "
                                   "to set the exact scale (C)"))
        self.btn_cal.clicked.connect(self.calibrate_requested.emit)
        self.btn_cal_reset = QPushButton(tr("Reset"))
        self.btn_cal_reset.clicked.connect(self.calibration_reset.emit)
        row.addWidget(self.btn_cal)
        row.addWidget(self.btn_cal_reset)
        row.addStretch(1)
        sec.add_layout(row)
        self.set_calibration(0.0)
        # ---- area to convert ----
        self.area_label = label("", "muted", wrap=True)
        sec.add(self.area_label)
        arow = QHBoxLayout()
        arow.setSpacing(6)
        self.btn_area = QPushButton(icon("area"), tr("Select area…"))
        self.btn_area.setToolTip(tr("Drag a rectangle on the sheet: only that "
                                    "part is converted (A)"))
        self.btn_area.clicked.connect(self.area_requested.emit)
        self.btn_area_clear = QPushButton(tr("Whole sheet"))
        self.btn_area_clear.setToolTip(tr("Convert the whole sheet again"))
        self.btn_area_clear.clicked.connect(self.area_cleared.emit)
        arow.addWidget(self.btn_area)
        arow.addWidget(self.btn_area_clear)
        arow.addStretch(1)
        sec.add_layout(arow)
        self.set_area(None, "")

    def _geometry_section(self, sec):
        self.fit_arcs = sec.add(self._check(
            tr("Rebuild arcs and circles"),
            tr("PDF curves that are circular become true ARC and CIRCLE "
               "entities.")))
        self.join_polylines = sec.add(self._check(
            tr("Join segments into polylines"),
            tr("Touching segments with the same style become one polyline.")))
        self.join_splines = sec.add(self._check(
            tr("Join curves into single splines"),
            tr("Curves drawn in several pieces become one exact SPLINE.")))
        self.precision = self._combo(
            [(tr("Fine"), "fine"), (tr("Normal"), "normal"),
             (tr("Loose"), "loose")],
            tr("How strictly a curve must match a circle to become an arc."))
        self._row(sec, tr("Curve precision"), self.precision)
        self.hatches = sec.add(self._check(
            tr("Solid fills as hatches"),
            tr("Filled areas become solid HATCH entities on layer HATCH.")))
        self.hatch_patterns = sec.add(self._check(
            tr("Rebuild hatch patterns"),
            tr("CAD programs print hatches as hundreds of separate lines, "
               "dashes and dots: they become one pattern HATCH — parallel "
               "lines, or the standard pattern they come from (sand, "
               "concrete, gravel, earth, brick, insulation, dots) at its "
               "measured scale and angle.")))
        self.merge_dashes = sec.add(self._check(
            tr("Rebuild dashed lines"),
            tr("CAD programs print axes and hidden lines as separate dashes: "
               "they become one line with its linetype (dash lengths "
               "measured).")))
        self.ignore_white = sec.add(self._check(
            tr("Ignore white masks, white lines and page backgrounds"),
            tr("White elements are invisible on the PDF sheet; in CAD they "
               "would show or hide the drawing. Hatches keep a hole under "
               "the white text masks.")))

    def _text_section(self, sec):
        self.text_entities = sec.add(self._check(
            tr("Export text"), tr("PDF text becomes editable TEXT entities.")))
        self.group_mtext = sec.add(self._check(
            tr("Group stacked lines into paragraphs (MTEXT)"),
            tr("Left-aligned lines of the same size become one MTEXT "
               "paragraph (notes, title block).")))
        self.text_factor = QDoubleSpinBox()
        self.text_factor.setRange(0.4, 1.2)
        self.text_factor.setSingleStep(0.05)
        self.text_factor.setDecimals(2)
        self.text_factor.setToolTip(tr("Cap height relative to the PDF font "
                                       "size. 0.70 suits most CAD fonts."))
        self.text_factor.valueChanged.connect(self._on_change)
        self._row(sec, tr("Text height ratio"), self.text_factor)
        self.shx = sec.add(self._check(
            tr("Recover text drawn as strokes or outlines"),
            tr("AutoCAD prints SHX and TrueType text as lines or filled "
               "outlines and hides the real text in the PDF. The real text "
               "is used (layer TEXT_SHX); the strokes go to layer "
               "TEXT_SHX_STROKES, switched off.")))

    def _dims_section(self, sec):
        self.dims = sec.add(self._check(
            tr("Dimensions with arrows"),
            tr("Arrow + line + arrow + value becomes a real DIMENSION "
               "entity.")))
        self.ticks = sec.add(self._check(
            tr("Dimensions with tick marks"),
            tr("Architectural dimensions with oblique ticks become DIMENSION "
               "entities.")))
        self.leaders = sec.add(self._check(
            tr("Leaders (arrow + note)"),
            tr("Arrow + line + note becomes a leader.")))
        sec.add(label(tr("Values always keep the original PDF text. "
                         "Unmatched values go to layer DIM_RAW for review."),
                      "caption", wrap=True))

    def _layers_section(self, sec):
        self.pdf_layers = sec.add(self._check(
            tr("Keep the PDF's own layers"),
            tr("Layers already present in the PDF keep their names.")))
        self.layer_mode = self._combo(
            [(tr("Colour + lineweight + linetype"), "style"),
             (tr("Colour only"), "color"),
             (tr("Single geometry layer"), "single")],
            tr("How geometry layers are created when the PDF has no layers."))
        self._row(sec, tr("Layer naming"), self.layer_mode, stacked=True)
        self.linetypes = sec.add(self._check(
            tr("Recognise linetypes (axis, hidden…)"),
            tr("Dash patterns become CENTER, DASHED, DASHDOT or PHANTOM "
               "linetypes.")))
        self.color_mode = self._combo(
            [(tr("AutoCAD Color Index"), "aci"),
             (tr("True colour (exact RGB)"), "true")],
            tr("ACI colours work with CTB plot styles; true colour keeps the "
               "exact PDF colour."))
        self._row(sec, tr("Colours"), self.color_mode, stacked=True)
        self.blocks = sec.add(self._check(
            tr("Detect repeated symbols as blocks"),
            tr("Identical symbols repeated on the sheet become one BLOCK with "
               "insertions.")))
        self.repeats = QSpinBox()
        self.repeats.setRange(2, 50)
        self.repeats.setToolTip(tr("A symbol must appear at least this many "
                                   "times to become a block."))
        self.repeats.valueChanged.connect(self._on_change)
        self._row(sec, tr("Minimum occurrences"), self.repeats)
        self.block_rotations = sec.add(self._check(
            tr("Also match rotated and mirrored copies"),
            tr("A symbol turned by 90, 180 or 270 degrees, or mirrored, uses "
               "the same block (insertion with rotation / mirroring).")))

    def _scan_section(self, sec):
        self.raster = sec.add(self._check(
            tr("Trace lines and circles"),
            tr("Scanned pages are vectorised (lines, circles) on layer "
               "TRACE_LINES.")))
        self.ocr = sec.add(self._check(
            tr("Read text with OCR"),
            tr("Text on scanned pages is read by the OCR built into "
               "ConvertCAD (PP-OCR models), on this computer, at any "
               "angle.")))
        # languages: only the installed ones are listed (filled by
        # _fill_ocr_langs); others are downloaded with the button below
        self.ocr_lang = self._combo(
            [], tr("Languages read on scanned pages. For a drawing that mixes "
                   "two scripts (e.g. French and Arabic), choose \"English, "
                   "French… + Arabic\". Other languages: \"OCR languages and "
                   "models…\"."))
        self.ocr_lang.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.ocr_lang.setMinimumContentsLength(16)
        self._row(sec, tr("OCR languages"), self.ocr_lang, stacked=True)
        self.ocr_quality = self._combo(
            [(tr(OCR_QUALITIES[k]), k) for k in OCR_QUALITIES],
            tr("Standard: the built-in model, fast, right for most drawings. "
               "Maximum: larger models, slightly better on poor scans but "
               "about 20 times slower (download them first)."))
        self._row(sec, tr("OCR accuracy"), self.ocr_quality, stacked=True)
        self.btn_ocr_models = QPushButton(icon("save"),
                                          tr("OCR languages and models…"))
        self.btn_ocr_models.setToolTip(tr(
            "Download other OCR languages (Arabic, Cyrillic, Greek…) or the "
            "maximum accuracy models, or install them from files."))
        self.btn_ocr_models.clicked.connect(self.ocr_models_requested)
        sec.add(self.btn_ocr_models)
        self.dpi = self._combo([(f"{d} dpi", d) for d in RASTER_DPI_CHOICES],
                               tr("Higher resolution traces finer details "
                                  "but takes longer."))
        self._row(sec, tr("Scan resolution"), self.dpi)
        self.text_layer = sec.add(self._check(
            tr("Use the PDF's existing text layer"),
            tr("When a scanned PDF is already searchable, its text is used "
               "instead of OCR.")))
        self.images = sec.add(self._check(
            tr("Keep raster images (locked layer)"),
            tr("Embedded images and scans are kept on the locked layer "
               "IMG_RASTER for checking.")))
        self.ocr_status = label("", "caption", wrap=True)
        sec.add(self.ocr_status)

    def _output_section(self, sec):
        self.output_format = self._combo(
            [(tr("DXF drawing"), "dxf"),
             (tr("DWG drawing (AutoCAD 2000 format)"), "dwg")],
            tr("DWG files are written by the free GNU LibreDWG converter "
               "included with ConvertCAD, in the AutoCAD 2000 format that "
               "every AutoCAD version opens."))
        self._row(sec, tr("File format"), self.output_format, stacked=True)
        self.dxf_version = self._combo(
            [(f"{k}  —  {tr(v)}", k) for k, v in DXF_VERSIONS.items()],
            tr("R2018 suits current CAD software; R12 suits old CNC "
               "machines."))
        self._row(sec, tr("DXF version"), self.dxf_version, stacked=True)
        self.page_mode = self._combo(
            [(tr("One DXF, sheets side by side"), "single"),
             (tr("One DXF per sheet"), "split")],
            tr("With several sheets: one file with sheets side by side, or "
               "one file per sheet."))
        self._row(sec, tr("Multi-page output"), self.page_mode, stacked=True)
        self.write_log = sec.add(self._check(
            tr("Write a conversion log next to the DXF"), ""))
        self.open_folder = QCheckBox(tr("Open the folder after saving"))
        self.open_folder.setChecked(self.settings.open_folder_after_save)
        self.open_folder.toggled.connect(self._on_open_folder)
        sec.add(self.open_folder)

    # ---- Options <-> widgets -------------------------------------------------------------
    def scale_denominator(self) -> float:
        txt = self.scale.currentText().strip().replace(",", ".")
        m = re.match(r"^(?:1\s*[:/]\s*)?(\d+(?:\.\d+)?)$", txt)
        try:
            return max(float(m.group(1)), 1e-6) if m else 50.0
        except ValueError:
            return 50.0

    def set_scale_denominator(self, den: float) -> None:
        text = f"1:{den:g}"
        i = self.scale.findText(text)
        if i >= 0:
            self.scale.setCurrentIndex(i)
        else:
            self.scale.setEditText(text)

    def options(self) -> Options:
        return Options(
            fit_arcs=self.fit_arcs.isChecked(),
            join_polylines=self.join_polylines.isChecked(),
            join_splines=self.join_splines.isChecked(),
            curve_precision=self.precision.currentData(),
            hatches=self.hatches.isChecked(),
            hatch_patterns=self.hatch_patterns.isChecked(),
            merge_dashes=self.merge_dashes.isChecked(),
            ignore_white_fills=self.ignore_white.isChecked(),
            ignore_background_fills=self.ignore_white.isChecked(),
            text_entities=self.text_entities.isChecked(),
            group_mtext=self.group_mtext.isChecked(),
            text_height_factor=round(self.text_factor.value(), 3),
            shx_comments=self.shx.isChecked(),
            dimensions=self.dims.isChecked(),
            tick_dimensions=self.ticks.isChecked(),
            leaders=self.leaders.isChecked(),
            use_pdf_layers=self.pdf_layers.isChecked(),
            layer_mode=self.layer_mode.currentData(),
            recognize_linetypes=self.linetypes.isChecked(),
            color_mode=self.color_mode.currentData(),
            block_detection=self.blocks.isChecked(),
            block_min_repeats=self.repeats.value(),
            block_rotations=self.block_rotations.isChecked(),
            raster_mode=self.raster.isChecked(),
            ocr=self.ocr.isChecked(),
            ocr_lang=self.ocr_lang.currentData() or "latin",
            ocr_quality=self.ocr_quality.currentData(),
            raster_dpi=self.dpi.currentData(),
            use_pdf_text_layer=self.text_layer.isChecked(),
            include_images=self.images.isChecked(),
            units=self.units.currentData(),
            scale_denominator=self.scale_denominator(),
            calibrated_units_per_pt=self._cal_units_per_pt,
            auto_scale=self.auto_scale.isChecked(),
            clip_rect=list(self._clip_rect) if self._clip_rect else None,
            output_format=self.output_format.currentData(),
            dxf_version=self.dxf_version.currentData(),
            page_mode=self.page_mode.currentData(),
            write_log=self.write_log.isChecked(),
        )

    def set_options(self, o: Options) -> None:
        self._loading = True
        try:
            for cb, v in ((self.fit_arcs, o.fit_arcs),
                          (self.join_polylines, o.join_polylines),
                          (self.join_splines, o.join_splines),
                          (self.hatches, o.hatches),
                          (self.hatch_patterns, o.hatch_patterns),
                          (self.merge_dashes, o.merge_dashes),
                          (self.ignore_white, o.ignore_white_fills),
                          (self.text_entities, o.text_entities),
                          (self.group_mtext, o.group_mtext),
                          (self.shx, o.shx_comments),
                          (self.dims, o.dimensions),
                          (self.ticks, o.tick_dimensions),
                          (self.leaders, o.leaders),
                          (self.pdf_layers, o.use_pdf_layers),
                          (self.linetypes, o.recognize_linetypes),
                          (self.blocks, o.block_detection),
                          (self.block_rotations, o.block_rotations),
                          (self.raster, o.raster_mode), (self.ocr, o.ocr),
                          (self.text_layer, o.use_pdf_text_layer),
                          (self.images, o.include_images),
                          (self.auto_scale, o.auto_scale),
                          (self.write_log, o.write_log)):
                cb.setChecked(bool(v))
            for combo, v in ((self.precision, o.curve_precision),
                             (self.layer_mode, o.layer_mode),
                             (self.color_mode, o.color_mode),
                             (self.ocr_quality, o.ocr_quality),
                             (self.output_format, o.output_format),
                             (self.dpi, o.raster_dpi),
                             (self.units, o.units),
                             (self.dxf_version, o.dxf_version),
                             (self.page_mode, o.page_mode)):
                i = combo.findData(v)
                if i >= 0:
                    combo.setCurrentIndex(i)
            self.text_factor.setValue(o.text_height_factor)
            self.repeats.setValue(o.block_min_repeats)
            self.set_scale_denominator(o.scale_denominator)
            self._fill_ocr_langs(o.ocr_lang)
        finally:
            self._loading = False
        self._update_enabled()
        self.refresh_ocr_status()

    def _on_change(self, *_):
        if self._loading:
            return
        self.refresh_ocr_status()
        self._update_enabled()
        self._update_modified()
        self._refresh_cal_label()
        self.changed.emit()

    def _on_open_folder(self, checked: bool) -> None:
        self.settings.open_folder_after_save = checked

    def _update_enabled(self) -> None:
        self.ticks.setEnabled(self.dims.isChecked())
        for w in (self.group_mtext, self.text_factor, self.shx):
            w.setEnabled(self.text_entities.isChecked())
        self.repeats.setEnabled(self.blocks.isChecked())
        self.block_rotations.setEnabled(self.blocks.isChecked())
        scan_ocr = self.ocr.isChecked()
        for w in (self.ocr_lang, self.ocr_quality):
            w.setEnabled(scan_ocr)
        dwg = self.output_format.currentData() == "dwg"
        self.dxf_version.setEnabled(not dwg)
        self.dxf_version.setToolTip(
            tr("DWG files are always written in the AutoCAD 2000 format.")
            if dwg else tr("R2018 suits current CAD software; R12 suits old "
                           "CNC machines."))
        self.dpi.setEnabled(self.raster.isChecked() or scan_ocr)

    # ---- calibration display -------------------------------------------------------------
    def set_calibration(self, units_per_pt: float) -> None:
        self._cal_units_per_pt = units_per_pt
        self._refresh_cal_label()
        self.scale.setEnabled(units_per_pt <= 0)
        self.auto_scale.setEnabled(units_per_pt <= 0)   # calibration wins
        self.btn_cal_reset.setVisible(units_per_pt > 0)

    def _refresh_cal_label(self) -> None:
        u = self.units.currentData() or "mm"
        if self._cal_units_per_pt > 0:
            den = effective_denominator(self._cal_units_per_pt, u)
            self.cal_label.setText(tr(
                "Calibrated: 1 pt = {v} {u} (about 1:{den})",
                v=f"{self._cal_units_per_pt:.5g}", u=u, den=_fmt_den(den)))
            self.cal_label.setProperty("role", "ok")
        elif self.auto_scale.isChecked():
            self.cal_label.setText(tr("Not calibrated: each sheet uses the "
                                      "scale written on it, else the scale "
                                      "above."))
            self.cal_label.setProperty("role", "muted")
        else:
            self.cal_label.setText(tr("Not calibrated: the drawing scale "
                                      "above is used."))
            self.cal_label.setProperty("role", "muted")
        restyle(self.cal_label)

    def set_stale(self, stale: bool) -> None:
        self.notice.setText(tr("Options changed since the last conversion. "
                               "Convert again to update the result."))
        self.notice.setVisible(stale)

    # ---- area ----------------------------------------------------------------------------
    def set_area(self, rect, text: str) -> None:
        """rect: [x0, y0, x1, y1] in page points, or None (whole sheet)."""
        self._clip_rect = list(rect) if rect else None
        self._area_text = text
        if self._clip_rect:
            self.area_label.setText(tr("Area: {size} — only this part of each "
                                       "sheet is converted.", size=text))
            self.area_label.setProperty("role", "ok")
        else:
            self.area_label.setText(tr("Area: whole sheet."))
            self.area_label.setProperty("role", "muted")
        self.btn_area_clear.setVisible(bool(self._clip_rect))
        restyle(self.area_label)

    def clip_rect(self):
        return list(self._clip_rect) if self._clip_rect else None

    # ---- OCR languages and models -------------------------------------------------
    @staticmethod
    def ocr_lang_label(key: str) -> str:
        """'latin+arabic' -> 'English, French… + Arabic', in the interface
        language."""
        return " + ".join(tr(n) for n in language_set(key).names())

    def _fill_ocr_langs(self, select: str) -> None:
        """List the installed OCR languages (cheap: files are only looked
        for, no model is loaded). A choice whose model is missing (settings
        copied from another computer, model removed) stays visible, marked,
        so it is never changed silently."""
        from ..core.ocr import language_choices
        select = language_set(select).key
        self.ocr_lang.blockSignals(True)
        self.ocr_lang.clear()
        for key, _label, _ok in language_choices():
            self.ocr_lang.addItem(self.ocr_lang_label(key), key)
        if self.ocr_lang.findData(select) < 0:
            self.ocr_lang.addItem(self.ocr_lang_label(select) + "  "
                                  + tr("(not downloaded)"), select)
        self.ocr_lang.setCurrentIndex(max(self.ocr_lang.findData(select), 0))
        self.ocr_lang.blockSignals(False)

    def refresh_ocr(self) -> None:
        """After models were downloaded or removed."""
        was = self._loading
        self._loading = True
        try:
            self._fill_ocr_langs(self.ocr_lang.currentData() or "latin")
        finally:
            self._loading = was
        self.refresh_ocr_status()

    def refresh_ocr_status(self) -> None:
        from ..core import ocr as ocr_engines
        from ..core.ocr_catalog import MAXIMUM
        maximum_ok = ocr_engines.pack_usable(MAXIMUM)
        i = self.ocr_quality.findData("maximum")
        if i >= 0:
            text = tr(OCR_QUALITIES["maximum"])
            self.ocr_quality.setItemText(
                i, text if maximum_ok else text + "  " + tr("(not downloaded)"))
        key = self.ocr_lang.currentData() or "latin"
        missing = [tr(BY_ID[p].label) for p in language_set(key).packs
                   if not ocr_engines.pack_usable(BY_ID[p])]
        if self.ocr_quality.currentData() == "maximum" and not maximum_ok:
            missing.append(tr(MAXIMUM.label))
        if not ocr_engines.available():
            text, role = tr("OCR not available: the OCR engine is not "
                            "installed. Tracing still works."), "warn"
        elif missing:
            text, role = tr("Not downloaded: {names}. The built-in model is "
                            "used instead.", names=", ".join(missing)), "warn"
        else:
            text, role = tr("OCR ready, offline."), "ok"
        self.ocr_status.setText(text)
        self.ocr_status.setProperty("role", role)
        restyle(self.ocr_status)

    def save_to_settings(self) -> None:
        opt = self.options()
        opt.calibrated_units_per_pt = 0.0       # calibration is per drawing
        opt.pages = None
        opt.clip_rect = None                    # the area too
        self.settings.options = opt.to_dict()
