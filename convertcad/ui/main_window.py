"""
main_window.py — the ConvertCAD window: wiring of every panel and action.

Layout
------
  menu bar
  command bar   Open | Pan Calibrate Measure Area | Fit - + |   Convert  Save  Batch | Theme Help
  ┌ Sheets ┐┌ Source PDF | DXF result ───────────────┐┌ Settings | Layers | Report ┐
  │ thumbs ││  viewer                                 ││                            │
  │        ││─────────────────────────────────────────││                            │
  │        ││  Activity log                           ││                            │
  └────────┘└─────────────────────────────────────────┘└────────────────────────────┘
  title-block status bar: Sheet | Paper | Scale | Cursor | Snap | Zoom | message

Workflow (one primary action at a time):
  open  ->  check scale (calibrate / measure), optionally select an area
  ->  Convert (background process, cancellable)  ->  review (DXF preview,
  overlay check on the PDF, layers, report)  ->  Save as DXF or DWG

Start-up speed: PyMuPDF, ezdxf and NumPy are NOT imported here. They are
imported where first needed (opening a PDF, saving) and warmed up in the
background right after the window appears (see app.py).
"""

import math
import os
import re
import shutil
import tempfile
from typing import List, Optional

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QThread, QTimer, \
    Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
                               QHBoxLayout, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSizePolicy, QSlider, QSplitter,
                               QStackedWidget,
                               QTabBar, QTabWidget, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION
from ..config import settings_dir
from ..core.constants import UNITS
from ..core.jobs import JobRunner
from ..core.report import ConversionReport
from ..core.units import compute_scale, effective_denominator
from ..i18n import LANGUAGES, tr, tr_paper, tr_progress
from . import theme
from .batch_dialog import BatchDialog
from .dialogs import (AboutDialog, CalibrateDialog, GuideDialog,
                      ShortcutsDialog, TermsDialog, open_folder)
from .dxf_view import DxfView
from .empty_state import EmptyState
from .icons import app_icon, icon, icon_size
from .layers_panel import LayersPanel
from .ocr_models_dialog import OcrModelsDialog, stop_downloads
from .options_panel import OptionsPanel
from .pages_panel import PagesPanel
from .pdf_view import PdfView, format_length
from .report_panel import ActivityPanel, ReportPanel
from .statusbar import TitleBlockBar
from .widgets import Toast, restyle


class _SaveThread(QThread):
    """Saves (layer edits + images + log, and DWG writing) off the
    interface thread: a large drawing takes several seconds."""
    done = Signal(object, str)                 # list of saved paths, error

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs                       # [(callable, args, kwargs)]

    def run(self) -> None:
        saved = []
        try:
            for fn, args, kwargs in self.jobs:
                saved.append(fn(*args, **kwargs).dxf_path)
            self.done.emit(saved, "")
        except Exception as exc:
            self.done.emit(saved, str(exc))


class _UpdateThread(QThread):
    """Asks GitHub for the latest release (core/updates.py), off the
    interface thread."""
    done = Signal(object, str)                 # UpdateInfo or None, error

    def run(self) -> None:
        from ..core import updates
        try:
            self.done.emit(updates.check(), "")
        except Exception as exc:                # UpdateError, or anything
            self.done.emit(None, str(exc))


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1440, 880)
        self.setMinimumSize(1060, 660)

        self.doc = None
        self.doc_info = None
        self.pdf_path = ""
        self.cal_mm_per_pt = 0.0         # calibration, canonical (mm / pt)
        self.result: Optional[dict] = None
        self._result_index = 0
        self._busy = False
        self.runner = JobRunner()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(60)
        self.poll_timer.timeout.connect(self._poll_job)
        self.temp_root = tempfile.mkdtemp(prefix="convertcad_")
        self._run_counter = 0
        self._pending_save = ""                 # DWG save waiting for a run
        self._save_thread: Optional[_SaveThread] = None
        self._update_thread: Optional[_UpdateThread] = None

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_body()
        self._connect()
        self._restore_layout()
        self._update_state()
        self.activity.log(f"{APP_NAME} {APP_VERSION} — " + tr("Ready"))
        if self.settings.check_updates:          # opt-in, off by default
            QTimer.singleShot(4000, lambda: self.check_updates(quiet=True))

    # =====================================================================
    # Construction
    # =====================================================================
    def _act(self, text, slot=None, shortcut=None, icon_name=None,
             checkable=False, tip=None) -> QAction:
        a = QAction(tr(text), self)
        if slot:
            a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon_name:
            a.setIcon(icon(icon_name))
            a.setData(icon_name)
        a.setCheckable(checkable)
        if tip:
            a.setToolTip(tr(tip))
            a.setStatusTip(tr(tip))
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        A = self._act
        self.a_open = A("Open PDF…", self.open_dialog, "Ctrl+O", "open",
                        tip="Open a PDF drawing (Ctrl+O)")
        self.a_sample = A("Open the sample plan", self.open_sample,
                          icon_name="sample")
        self.a_close = A("Close the drawing", self.close_drawing, "Ctrl+W")
        self.a_convert = A("Convert", self.convert_or_cancel, "Ctrl+Return",
                           "convert",
                           tip="Convert the selected sheets to DXF (Ctrl+Enter)")
        self.a_save = A("Save DXF…", self.save_dxf, "Ctrl+S", "save",
                        tip="Save the reviewed DXF (Ctrl+S)")
        self.a_batch = A("Convert a folder…", self.open_batch, "Ctrl+B",
                         "batch", tip="Convert every PDF of a folder (Ctrl+B)")
        self.a_report = A("Save the report…",
                          lambda: self.report_panel.save_txt())
        self.a_exit = A("Exit", self.close, "Ctrl+Q")
        self.a_fit = A("Fit the sheet", self.fit_view, "F", "fit")
        self.a_zin = A("Zoom in", lambda: self.current_view().zoom_by(1.25),
                       "Ctrl++", "zoom_in")
        self.a_zout = A("Zoom out", lambda: self.current_view().zoom_by(0.8),
                        "Ctrl+-", "zoom_out")
        self.a_src = A("Source PDF", lambda: self.show_view(0), "Ctrl+1")
        self.a_res = A("DXF result", lambda: self.show_view(1), "Ctrl+2")
        self.a_pan = A("Pan", lambda: self.set_tool("pan"), "Esc", "pan",
                       checkable=True, tip="Pan and zoom the view (Esc)")
        self.a_cal = A("Calibrate scale", lambda: self.set_tool("calibrate"),
                       "C", "calibrate", checkable=True,
                       tip="Click two points with a known distance to set "
                           "the exact scale (C)")
        self.a_meas = A("Measure distance", lambda: self.set_tool("measure"),
                        "M", "measure", checkable=True,
                        tip="Click two points to measure a real distance (M)")
        self.a_area = A("Select area", lambda: self.set_tool("area"), "A",
                        "area", checkable=True,
                        tip="Drag a rectangle on the sheet: only that part "
                            "is converted (A)")
        group = QActionGroup(self)
        for a in (self.a_pan, self.a_cal, self.a_meas, self.a_area):
            group.addAction(a)
        self.a_pan.setChecked(True)
        self.a_clear_meas = A("Clear measurements", self._clear_measurements,
                              "Del", "clear")
        self.a_cal_reset = A("Reset calibration", self.reset_calibration)
        self.a_area_clear = A("Convert the whole sheet", self.clear_area)
        self.a_overlay = A("Overlay the PDF on the DXF", self._toggle_overlay,
                           "O", "overlay", checkable=True,
                           tip="Show the PDF sheet under the DXF result to "
                               "check the conversion (O)")
        self.a_snap = A("Object snap", self._toggle_snap, "F3",
                        checkable=True)
        self.a_snap.setChecked(True)
        self.a_next = A("Next sheet", lambda: self._step_sheet(1), "PgDown")
        self.a_prev = A("Previous sheet", lambda: self._step_sheet(-1), "PgUp")
        self.a_theme = A("Theme", self.toggle_theme, icon_name="theme",
                         tip="Switch between dark and light theme")
        self.a_guide = A("User guide", lambda: GuideDialog(self).exec(), "F1",
                         "help")
        self.a_keys = A("Keyboard shortcuts",
                        lambda: ShortcutsDialog(self).exec())
        self.a_ocr = A("OCR guide (scanned PDFs)",
                       lambda: GuideDialog(self, "ocr").exec())
        self.a_ocr_models = A("OCR languages and models…",
                              self.open_ocr_models,
                              tip="Download other OCR languages or the "
                                  "maximum accuracy models")
        self.a_terms = A("Terms of use",
                         lambda: TermsDialog(self, gate=False).exec())
        self.a_about = A("About ConvertCAD", lambda: AboutDialog(self).exec())
        self.a_updates = A("Check for updates…", self.check_updates,
                           tip="Ask GitHub whether a newer ConvertCAD exists "
                               "(nothing is sent, nothing is installed)")
        self.a_updates_auto = A("Check for updates at startup",
                                self._toggle_update_check, checkable=True)
        self.a_updates_auto.setChecked(bool(self.settings.check_updates))
        self.a_settings_dir = A("Open the settings folder",
                                lambda: open_folder(settings_dir()))

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu(tr("Open recent"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addAction(self.a_sample)
        m.addAction(self.a_close)
        m.addSeparator()
        m.addAction(self.a_convert)
        m.addAction(self.a_save)
        m.addAction(self.a_batch)
        m.addSeparator()
        m.addAction(self.a_report)
        m.addSeparator()
        m.addAction(self.a_exit)
        v = mb.addMenu(tr("&View"))
        for a in (self.a_fit, self.a_zin, self.a_zout):
            v.addAction(a)
        v.addSeparator()
        v.addAction(self.a_src)
        v.addAction(self.a_res)
        v.addAction(self.a_overlay)
        v.addSeparator()
        panels = v.addMenu(tr("Panels"))
        self.a_show_pages = panels.addAction(tr("Sheets panel"))
        self.a_show_right = panels.addAction(tr("Settings panel"))
        self.a_show_activity = panels.addAction(tr("Activity panel"))
        for a in (self.a_show_pages, self.a_show_right, self.a_show_activity):
            a.setCheckable(True)
            a.setChecked(True)
        v.addSeparator()
        tm = v.addMenu(tr("Theme"))
        self.a_dark = tm.addAction(tr("Dark"), lambda: self.set_theme("dark"))
        self.a_light = tm.addAction(tr("Light"),
                                    lambda: self.set_theme("light"))
        lm = v.addMenu(tr("Language"))
        for code, name in LANGUAGES.items():
            lm.addAction(name, lambda c=code: self.set_language(c))
        t = mb.addMenu(tr("&Tools"))
        for a in (self.a_pan, self.a_cal, self.a_meas, self.a_area):
            t.addAction(a)
        t.addSeparator()
        t.addAction(self.a_clear_meas)
        t.addAction(self.a_cal_reset)
        t.addAction(self.a_area_clear)
        t.addSeparator()
        t.addAction(self.a_snap)
        t.addSeparator()
        t.addAction(self.a_next)
        t.addAction(self.a_prev)
        t.addSeparator()
        t.addAction(self.a_ocr_models)
        h = mb.addMenu(tr("&Help"))
        for a in (self.a_guide, self.a_keys, self.a_ocr):
            h.addAction(a)
        h.addSeparator()
        h.addAction(self.a_updates)
        h.addAction(self.a_updates_auto)
        h.addSeparator()
        h.addAction(self.a_terms)
        h.addAction(self.a_settings_dir)
        h.addAction(self.a_about)

    def _tool_button(self, action: QAction, text_beside=True) -> QToolButton:
        b = QToolButton()
        b.setDefaultAction(action)
        b.setIconSize(icon_size(18))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                             if text_beside else
                             Qt.ToolButtonStyle.ToolButtonIconOnly)
        return b

    def _build_toolbar(self) -> None:
        tb = QToolBar()
        tb.setObjectName("CommandBar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.btn_open = self._tool_button(self.a_open)
        self.btn_open.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        open_menu = QMenu(self.btn_open)
        open_menu.aboutToShow.connect(lambda: self._fill_recent(open_menu))
        self.btn_open.setMenu(open_menu)
        tb.addWidget(self.btn_open)
        tb.addSeparator()
        # buttons that drop their label when the window is too narrow for
        # the labels of the chosen language (_fit_toolbar)
        self._compact_buttons = []
        for a in (self.a_pan, self.a_cal, self.a_meas, self.a_area):
            b = self._tool_button(a)
            self._compact_buttons.append(b)
            tb.addWidget(b)
        tb.addSeparator()
        for a in (self.a_fit, self.a_zout, self.a_zin):
            b = self._tool_button(a, text_beside=a is self.a_fit)
            if a is self.a_fit:
                self._compact_buttons.append(b)
            tb.addWidget(b)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.btn_convert = self._tool_button(self.a_convert)
        self.btn_save = self._tool_button(self.a_save)
        self.btn_batch = self._tool_button(self.a_batch)
        for b in (self.btn_convert, self.btn_save, self.btn_batch):
            tb.addWidget(b)
        self._compact_buttons.append(self.btn_batch)
        tb.addSeparator()
        tb.addWidget(self._tool_button(self.a_theme, text_beside=False))
        help_btn = QToolButton()
        help_btn.setIcon(icon("help"))
        help_btn.setIconSize(icon_size(18))
        help_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hm = QMenu(help_btn)
        for a in (self.a_guide, self.a_keys, self.a_ocr, self.a_updates,
                  self.a_terms, self.a_about):
            hm.addAction(a)
        help_btn.setMenu(hm)
        help_btn.setProperty("iconName", "help")
        self.help_btn = help_btn
        tb.addWidget(help_btn)
        self.toolbar = tb

    def _build_body(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.setChildrenCollapsible(False)
        root.addWidget(self.main_split, 1)
        self.statusbar = TitleBlockBar()
        root.addWidget(self.statusbar)
        self.setCentralWidget(central)

        # left: sheets
        self.pages_panel = PagesPanel()
        self.main_split.addWidget(self.pages_panel)

        # centre: views + activity
        self.center_split = QSplitter(Qt.Orientation.Vertical)
        self.center_split.setChildrenCollapsible(False)
        self.center_stack = QStackedWidget()
        self.empty = EmptyState()
        self.center_stack.addWidget(self.empty)
        work = QWidget()
        wl = QVBoxLayout(work)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("Panel")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 0, 8, 0)
        self.view_tabs = QTabBar()
        self.view_tabs.addTab(tr("Source PDF"))
        self.view_tabs.addTab(tr("DXF result"))
        self.view_tabs.setDrawBase(False)
        self.view_tabs.setExpanding(False)
        bl.addWidget(self.view_tabs)
        bl.addStretch(1)
        self.overlay_btn = QToolButton()
        self.overlay_btn.setDefaultAction(self.a_overlay)
        self.overlay_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.overlay_btn.setIconSize(icon_size(16))
        self.overlay_btn.setText(tr("Overlay PDF"))
        self.overlay_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_slider.setRange(10, 90)
        self.overlay_slider.setValue(45)
        self.overlay_slider.setFixedWidth(110)
        self.overlay_slider.setToolTip(tr("Opacity of the PDF under the DXF"))
        self.overlay_slider.valueChanged.connect(
            lambda v: self.dxf_view.set_overlay_opacity(v / 100.0))
        bl.addWidget(self.overlay_btn)
        bl.addWidget(self.overlay_slider)
        self.result_combo = QComboBox()
        self.result_combo.setToolTip(tr("Sheet file"))
        self.result_combo.hide()
        bl.addWidget(self.result_combo)
        wl.addWidget(bar)
        self.view_stack = QStackedWidget()
        self.pdf_view = PdfView()
        self.dxf_view = DxfView()
        self.view_stack.addWidget(self.pdf_view)
        self.view_stack.addWidget(self.dxf_view)
        wl.addWidget(self.view_stack, 1)
        self.center_stack.addWidget(work)
        self.center_split.addWidget(self.center_stack)
        self.activity = ActivityPanel()
        self.center_split.addWidget(self.activity)
        self.center_split.setStretchFactor(0, 5)
        self.center_split.setStretchFactor(1, 1)
        self.main_split.addWidget(self.center_split)

        # right: settings / layers / report
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)
        self.options_panel = OptionsPanel(self.settings)
        self.layers_panel = LayersPanel()
        self.report_panel = ReportPanel(self.settings)
        self.right_tabs.addTab(self.options_panel, tr("Settings"))
        self.right_tabs.addTab(self.layers_panel, tr("Layers"))
        self.right_tabs.addTab(self.report_panel, tr("Report"))
        self.right_tabs.setMinimumWidth(330)
        self.main_split.addWidget(self.right_tabs)
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setStretchFactor(2, 0)
        self.main_split.setSizes([210, 900, 370])

        self.toast = Toast(self.center_stack)
        self.empty.set_recent(self.settings.existing_recent())

    def _connect(self) -> None:
        self.empty.open_requested.connect(self.open_dialog)
        self.empty.sample_requested.connect(self.open_sample)
        self.empty.recent_requested.connect(self.open_pdf)
        self.pages_panel.page_activated.connect(self.show_page)
        self.pages_panel.selection_changed.connect(self._update_state)
        self.view_tabs.currentChanged.connect(self.view_stack.setCurrentIndex)
        self.view_tabs.currentChanged.connect(self._on_view_changed)
        self.result_combo.currentIndexChanged.connect(self._on_result_file)
        self.pdf_view.cursor_moved.connect(self._on_cursor)
        self.pdf_view.cursor_left.connect(
            lambda: self.statusbar.cursor.set("–"))
        self.pdf_view.zoom_changed.connect(self._on_zoom)
        self.dxf_view.zoom_changed.connect(self._on_zoom)
        self.pdf_view.hint.connect(self.status)
        self.pdf_view.calibration_picked.connect(self._on_calibration_picked)
        self.pdf_view.measurement_added.connect(self._on_measured)
        self.pdf_view.area_selected.connect(self._on_area_selected)
        self.dxf_view.loaded.connect(self._on_dxf_loaded)
        self.dxf_view.selected.connect(self._on_entity_selected)
        self.pdf_view.tool_changed.connect(self._on_tool_changed)
        self.dxf_view.loading.connect(
            lambda on: self.status(tr("Rendering the DXF preview…")) if on
            else None)
        self.options_panel.changed.connect(self._on_options_changed)
        self.options_panel.calibrate_requested.connect(
            lambda: self.set_tool("calibrate"))
        self.options_panel.calibration_reset.connect(self.reset_calibration)
        self.options_panel.area_requested.connect(
            lambda: self.set_tool("area"))
        self.options_panel.area_cleared.connect(self.clear_area)
        self.options_panel.preset_message.connect(self.notify)
        self.options_panel.ocr_models_requested.connect(self.open_ocr_models)
        self.layers_panel.edits_changed.connect(self._on_layer_edits)
        self.report_panel.message.connect(self.notify)
        self.statusbar.snap_toggled.connect(self._on_snap_toggled)
        self.a_show_pages.toggled.connect(self.pages_panel.setVisible)
        self.a_show_right.toggled.connect(self.right_tabs.setVisible)
        self.a_show_activity.toggled.connect(self.activity.setVisible)
        snaps = {"end": self.settings.snap_end, "mid": self.settings.snap_mid,
                 "int": self.settings.snap_int,
                 "cen": self.settings.snap_center}
        self.statusbar.set_snaps(snaps)
        self.pdf_view.snap_modes = {k for k, v in snaps.items() if v}

    def _restore_layout(self) -> None:
        try:
            if self.settings.window_geometry:
                self.restoreGeometry(QByteArray.fromBase64(
                    self.settings.window_geometry.encode()))
            if self.settings.window_state:
                sizes = [int(x) for x in self.settings.window_state.split(",")]
                if len(sizes) == 5:
                    self.main_split.setSizes(sizes[:3])
                    self.center_split.setSizes(sizes[3:])
        except Exception:
            pass
        self.a_show_activity.setChecked(self.settings.show_activity)

    # =====================================================================
    # Helpers
    # =====================================================================
    def status(self, msg: str) -> None:
        self.statusbar.message.setText(msg)

    def notify(self, msg: str, level: str = "info") -> None:
        self.status(msg)
        self.activity.log(msg)
        self.toast.show_message(msg, level)

    def _on_entity_selected(self, info) -> None:
        """An entity was clicked in the DXF preview: show its layer."""
        if not info:
            self.layers_panel.table.clearSelection()
            self.status("")
            return
        if self.layers_panel.select_layer(info.get("layer", "")):
            self.right_tabs.setCurrentWidget(self.layers_panel)
        self.status(self.entity_text(info))

    def entity_text(self, info: dict) -> str:
        """'LINE — layer GEO_BLACK_035 — length 2,500.0 mm — size …'."""
        u = self.units()
        parts = [info.get("type", "?"),
                 tr("layer {name}", name=info.get("layer", "0"))]
        if "length" in info:
            parts.append(tr("length {v}", v=format_length(info["length"], u)))
        if "radius" in info:
            parts.append(tr("radius {v}", v=format_length(info["radius"], u)))
        if "measurement" in info:
            parts.append(tr("dimension {v}",
                            v=format_length(info["measurement"], u)))
        if info.get("text"):
            parts.append("« " + info["text"][:60] + " »")
        if info.get("block"):
            parts.append(tr("block {v}", v=info["block"]))
        if info.get("pattern"):
            parts.append(tr("pattern {v}", v=info["pattern"]))
        if info.get("vertices"):
            parts.append(tr("{n} vertices", n=info["vertices"]))
        bb = info.get("bbox")
        if bb and info.get("type") not in ("TEXT", "MTEXT"):
            parts.append(tr("size {w} × {h}", w=format_length(bb[2] - bb[0], u),
                            h=format_length(bb[3] - bb[1], u)))
        return "  —  ".join(parts)

    def current_view(self):
        return self.view_stack.currentWidget()

    def units(self) -> str:
        return self.options_panel.units.currentData() or "mm"

    def units_per_pt(self) -> float:
        u = self.units()
        if self.cal_mm_per_pt > 0:
            return self.cal_mm_per_pt * UNITS[u]["factor"]
        return compute_scale(u, self.options_panel.scale_denominator())

    def show_view(self, index: int) -> None:
        if self.doc is None:
            return
        self.view_tabs.setCurrentIndex(index)

    def fit_view(self) -> None:
        if self.doc is not None:
            self.current_view().fit()

    def _set_primary(self, button: QToolButton, primary: bool) -> None:
        button.setProperty("kind", "primary" if primary else "")
        name = button.defaultAction().data()
        color = theme.tok("on_accent") if primary and button.isEnabled() \
            else theme.tok("text")
        if name:
            button.defaultAction().setIcon(icon(name, color))
        restyle(button)

    def _update_state(self) -> None:
        has_doc = self.doc is not None
        has_result = bool(self.result and self.result.get("outputs"))
        pages = self.pages_panel.selected_pages() if has_doc else []
        for a in (self.a_pan, self.a_cal, self.a_meas, self.a_area,
                  self.a_fit, self.a_zin,
                  self.a_zout, self.a_close, self.a_clear_meas,
                  self.a_src, self.a_res, self.a_next, self.a_prev):
            a.setEnabled(has_doc)
        self.a_area_clear.setEnabled(bool(self.options_panel.clip_rect()))
        on_result = self.view_tabs.currentIndex() == 1 and has_result
        self.a_overlay.setEnabled(has_result)
        self.overlay_btn.setVisible(on_result)
        self.overlay_slider.setVisible(on_result and
                                       self.a_overlay.isChecked())
        self.a_convert.setEnabled(self._busy or (has_doc and bool(pages)))
        saving = self._save_thread is not None
        self.a_save.setEnabled(has_result and not self._busy and not saving)
        dwg = self.options_panel.output_format.currentData() == "dwg"
        self.a_save.setText(tr("Save DWG…") if dwg else tr("Save DXF…"))
        self.a_save.setToolTip(tr("Save the reviewed drawing (Ctrl+S)"))
        self.a_report.setEnabled(bool(self.result and self.result.get("report")))
        self.a_cal_reset.setEnabled(self.cal_mm_per_pt > 0)
        self.a_batch.setEnabled(not self._busy)
        if self._busy:
            self.a_convert.setText(tr("Cancel"))
            self.a_convert.setToolTip(tr("Stop the running conversion"))
            self.a_convert.setData("stop")
            self.btn_convert.setProperty("kind", "danger")
            self.a_convert.setIcon(icon("stop", theme.tok("err")))
            restyle(self.btn_convert)
        else:
            stale = bool(self.result and self.result.get("stale"))
            self.a_convert.setText(tr("Convert again") if has_result
                                   else tr("Convert"))
            self.a_convert.setToolTip(tr("Convert the selected sheets to DXF "
                                         "(Ctrl+Enter)"))
            self.a_convert.setData("convert")
            primary_convert = not has_result or stale
            self._set_primary(self.btn_convert, primary_convert)
            self._set_primary(self.btn_save, has_result and not stale)
        self.center_stack.setCurrentIndex(1 if has_doc else 0)
        title = APP_NAME
        if has_doc:
            title = f"{os.path.basename(self.pdf_path)} — {APP_NAME}"
            if has_result and not self.result.get("saved"):
                title = "● " + title
        self.setWindowTitle(title)
        self._update_scale_cell()

    def _update_scale_cell(self) -> None:
        if self.cal_mm_per_pt > 0:
            den = effective_denominator(self.units_per_pt(), self.units())
            self.statusbar.scale.set(f"{tr('Calibrated')}  ≈1:{den:.4g}")
        else:
            self.statusbar.scale.set(
                f"1:{self.options_panel.scale_denominator():g}  "
                f"{self.units()}")
        self.pdf_view.set_scale_info(self.units_per_pt(), self.units())

    # =====================================================================
    # Opening documents
    # =====================================================================
    def _confirm_discard(self, question: str) -> bool:
        if self.result and self.result.get("outputs") and \
                not self.result.get("saved"):
            r = QMessageBox.question(self, APP_NAME, tr(question))
            return r == QMessageBox.StandardButton.Yes
        return True

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open PDF…"), self.settings.last_open_dir,
            tr("PDF drawings (*.pdf)"))
        if path:
            self.open_pdf(path)

    def open_sample(self) -> None:
        from ..samples import make_sample_plan
        path = os.path.join(self.temp_root, "ConvertCAD sample plan.pdf")
        if not os.path.isfile(path):
            make_sample_plan(path)
        self.open_pdf(path, remember=False)
        self.options_panel.set_scale_denominator(100)

    def open_pdf(self, path: str, remember: bool = True) -> None:
        if self._busy:
            return
        if not path.lower().endswith(".pdf"):
            self.notify(tr("Only PDF files can be opened."), "warn")
            return
        if not self._confirm_discard("The result has not been saved. Open "
                                     "another drawing anyway?"):
            return
        self.status(tr("Opening {name}…", name=os.path.basename(path)))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from ..core.pdfinfo import inspect_document   # loads PyMuPDF
            info = inspect_document(path)
        finally:
            QApplication.restoreOverrideCursor()
        if info.encrypted:
            QMessageBox.warning(self, APP_NAME, tr(
                "This PDF is password-protected. Remove the password (print "
                "it to PDF) and try again."))
            return
        if info.error or info.page_count == 0:
            QMessageBox.warning(self, APP_NAME, tr("Cannot open this PDF.")
                                + "\n\n" + (info.error or ""))
            return
        self.close_drawing(ask=False)
        from ..core.compat import pymupdf
        self.doc = pymupdf.open(path)
        self.doc_info = info
        self.pdf_path = path
        if remember:
            self.settings.add_recent(path)
            self.settings.last_open_dir = os.path.dirname(path)
            self.settings.save()
        self.pdf_view.set_document(self.doc)
        self.pages_panel.load(self.doc, info.pages)
        self.view_tabs.setCurrentIndex(0)
        self.show_page(0)
        self._update_state()
        self.notify(tr("Opened {name}: {pages} sheet(s).",
                       name=os.path.basename(path), pages=info.page_count))
        self._hints_after_open(info)

    def _hints_after_open(self, info) -> None:
        """Smart help: scale written in the title block, scans, AutoCAD."""
        from ..core.pdfinfo import detect_scale
        try:
            text = self.doc[0].get_text("text")
        except Exception:
            text = ""
        den = detect_scale(text)
        if den and self.cal_mm_per_pt <= 0:
            self.options_panel.set_scale_denominator(den)
            self.notify(tr("Scale 1:{den} read from the drawing. Check it "
                           "with Measure before converting.", den=den))
        kinds = {p.kind for p in info.pages}
        if "scanned" in kinds:
            self.activity.log(tr("Scanned sheet detected: it will be traced "
                                 "and read with OCR."))
        if info.is_autocad:
            self.activity.log(tr("AutoCAD PDF detected: SHX text comments "
                                 "can be recovered (Settings > Text)."))

    def close_drawing(self, ask: bool = True) -> None:
        if ask and not self._confirm_discard(
                "The result has not been saved. Quit anyway?"):
            return
        self.pdf_view.set_document(None)
        self.pages_panel.clear()
        self._clear_result()
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.doc_info = None
        self.pdf_path = ""
        self.cal_mm_per_pt = 0.0
        self.options_panel.set_calibration(0.0)
        self.options_panel.set_area(None, "")
        self.pdf_view.set_calibration_overlay(None, None, "")
        self.statusbar.sheet.set("–")
        self.statusbar.paper.set("–")
        self.empty.set_recent(self.settings.existing_recent())
        self._update_state()

    def show_page(self, index: int) -> None:
        if self.doc is None:
            return
        self.pdf_view.show_page(index)
        self.pages_panel.set_current(index)
        info = self.doc_info.pages[index] if self.doc_info else None
        self.statusbar.sheet.set(f"{index + 1} / {self.doc.page_count}")
        if info:
            self.statusbar.paper.set(tr_paper(info.paper))
        if self.view_tabs.currentIndex() != 0:
            self.view_tabs.setCurrentIndex(0)

    def _step_sheet(self, step: int) -> None:
        if self.doc is None:
            return
        i = max(0, min(self.doc.page_count - 1,
                       self.pdf_view.page_index + step))
        self.show_page(i)

    # =====================================================================
    # Tools: pan / calibrate / measure
    # =====================================================================
    def set_tool(self, tool: str) -> None:
        if self.doc is None:
            return
        if self.view_tabs.currentIndex() != 0:
            self.view_tabs.setCurrentIndex(0)
        self.pdf_view.set_tool(tool)
        self.pdf_view.setFocus()

    def _on_tool_changed(self, tool: str) -> None:
        {"pan": self.a_pan, "calibrate": self.a_cal,
         "measure": self.a_meas, "area": self.a_area}[tool].setChecked(True)
        if tool == "pan":
            self.status(tr("Ready"))

    def _on_calibration_picked(self, a: QPointF, b: QPointF) -> None:
        length_pt = math.hypot(b.x() - a.x(), b.y() - a.y())
        if length_pt < 1e-6:
            return
        dlg = CalibrateDialog(length_pt, self.units(), self)
        if dlg.exec() != CalibrateDialog.DialogCode.Accepted:
            self.pdf_view.set_tool("pan")
            return
        upp = dlg.units_per_pt()
        self.cal_mm_per_pt = upp / UNITS[self.units()]["factor"]
        self.options_panel.set_calibration(self.units_per_pt())
        real = format_length(length_pt * self.units_per_pt(), self.units())
        self.pdf_view.set_calibration_overlay(a, b, real)
        den = effective_denominator(self.units_per_pt(), self.units())
        self.notify(tr("Scale calibrated: about 1:{den}.", den=f"{den:.4g}"),
                    "ok")
        self.pdf_view.set_tool("pan")
        self._mark_stale()
        self._update_state()

    def reset_calibration(self) -> None:
        if self.cal_mm_per_pt <= 0:
            return
        self.cal_mm_per_pt = 0.0
        self.options_panel.set_calibration(0.0)
        self.pdf_view.set_calibration_overlay(None, None, "")
        self.notify(tr("Calibration removed: the drawing scale is used."))
        self._mark_stale()
        self._update_state()

    def _on_measured(self, a: QPointF, b: QPointF) -> None:
        s = self.units_per_pt()
        dx, dy = (b.x() - a.x()) * s, -(b.y() - a.y()) * s
        d = math.hypot(dx, dy)
        ang = math.degrees(math.atan2(dy, dx))
        u = self.units()
        msg = tr("Distance {d}   ΔX {dx}   ΔY {dy}   Angle {a}°",
                 d=format_length(d, u), dx=format_length(dx, u),
                 dy=format_length(dy, u), a=f"{ang:.2f}")
        self.status(msg)
        self.activity.log(msg)

    # ---- selected area ----------------------------------------------------------
    def _area_text(self, rect: QRectF) -> str:
        s = self.units_per_pt()
        u = self.units()
        return (f"{format_length(rect.width() * s, u)} × "
                f"{format_length(rect.height() * s, u)}")

    def _on_area_selected(self, rect: QRectF) -> None:
        self.options_panel.set_area([rect.left(), rect.top(), rect.right(),
                                     rect.bottom()], self._area_text(rect))
        self.notify(tr("Area selected: {size}. Only this part of the sheet "
                       "will be converted.", size=self._area_text(rect)), "ok")
        self.pdf_view.set_tool("pan")
        self._mark_stale()
        self._update_state()

    def clear_area(self) -> None:
        if not self.options_panel.clip_rect():
            return
        self.options_panel.set_area(None, "")
        self.pdf_view.set_area(None)
        self.notify(tr("Whole sheet: the area selection was removed."))
        self._mark_stale()
        self._update_state()

    # ---- overlay check -------------------------------------------------------------
    def _toggle_overlay(self) -> None:
        if self.a_overlay.isChecked() and self.view_tabs.currentIndex() != 1:
            self.view_tabs.setCurrentIndex(1)
        self._apply_overlay()
        self._update_state()

    def _on_dxf_loaded(self, error: str) -> None:
        if not error:
            self._apply_overlay()

    def _apply_overlay(self) -> None:
        """PDF sheet(s) of the current result file, under the DXF, at the
        exact position and scale used by the conversion."""
        if not (self.a_overlay.isChecked() and self.result and self.doc):
            self.dxf_view.set_overlay([])
            return
        from PySide6.QtGui import QPixmap
        sheets = []
        rep = self.result["report"]
        for pl in rep.placements:
            if pl.get("file", 0) != self._result_index:
                continue
            pno = pl["page"] - 1
            if not 0 <= pno < self.doc.page_count:
                continue
            page = self.doc[pno]
            zoom = min(4000 / max(page.rect.width, page.rect.height, 1), 4.0)
            img = PdfView._render(page, zoom, None)
            upp = pl["width_pt"] * pl["scale"] / max(img.width(), 1)
            sheets.append((QPixmap.fromImage(img), pl["x_offset"],
                           pl["height_pt"] * pl["scale"], upp))
        self.dxf_view.set_overlay(sheets, self.overlay_slider.value() / 100.0)
        if sheets:
            self.status(tr("Overlay: the PDF is shown under the DXF. Lines "
                           "that do not match stand out."))

    def _clear_measurements(self) -> None:
        self.pdf_view.clear_measurements()

    def _toggle_snap(self) -> None:
        on = self.a_snap.isChecked()
        self.pdf_view.snap_enabled = on
        self.statusbar.set_snaps({k: on and k in self.pdf_view.snap_modes
                                  for k in ("end", "mid", "int", "cen")})

    def _on_snap_toggled(self, key: str, on: bool) -> None:
        modes = set(self.pdf_view.snap_modes)
        (modes.add if on else modes.discard)(key)
        self.pdf_view.snap_modes = modes
        self.pdf_view.snap_enabled = bool(modes)
        self.a_snap.setChecked(bool(modes))
        setattr(self.settings, {"end": "snap_end", "mid": "snap_mid",
                                "int": "snap_int", "cen": "snap_center"}[key],
                on)

    def _on_cursor(self, x: float, y: float) -> None:
        if self.doc is None:
            return
        s = self.units_per_pt()
        h = self.pdf_view.page_rect.height()
        u = self.units()
        self.statusbar.cursor.set(f"X {format_length(x * s, u)}   "
                                  f"Y {format_length((h - y) * s, u)}")

    def _on_zoom(self, scale: float) -> None:
        view = self.sender()
        if view is self.pdf_view:
            pct = scale / (self.logicalDpiX() / 72.0) * 100
        else:
            fit = self.dxf_view.fit_scale() or scale
            pct = scale / fit * 100
        self.statusbar.zoom.set(f"{pct:.0f} %")

    def _on_view_changed(self, index: int) -> None:
        view = self.current_view()
        self._on_zoom_for(view)
        self._update_state()

    def _on_zoom_for(self, view) -> None:
        if view is self.pdf_view:
            pct = view.current_scale() / (self.logicalDpiX() / 72.0) * 100
        else:
            fit = view.fit_scale() or view.current_scale() or 1
            pct = view.current_scale() / fit * 100
        self.statusbar.zoom.set(f"{pct:.0f} %")

    # =====================================================================
    # Conversion
    # =====================================================================
    def convert_or_cancel(self) -> None:
        if self._busy:
            self.runner.cancel()
            self.status(tr("Cancelling…"))
            return
        if self.doc is None:
            return
        pages = self.pages_panel.selected_pages()
        if not pages:
            self.notify(tr("Select at least one sheet to convert."), "warn")
            return
        opt = self.options_panel.options()
        opt.pages = pages
        opt.calibrated_units_per_pt = (self.units_per_pt()
                                       if self.cal_mm_per_pt > 0 else 0.0)
        self._run_counter += 1
        run_dir = os.path.join(self.temp_root, f"run{self._run_counter}")
        os.makedirs(run_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self.pdf_path))[0]
        dxf = os.path.join(run_dir, stem + ".dxf")
        self.options_panel.save_to_settings()
        self.settings.save()
        self.runner.start_convert(self.pdf_path, dxf, opt.to_dict())
        self._pending = {"dxf": dxf, "dir": run_dir, "options": opt}
        self._busy = True
        self.statusbar.set_progress(0.0)
        self.status(tr("Converting…"))
        self.activity.log(tr("Converting…") + f"  {os.path.basename(self.pdf_path)}"
                          f"  ({', '.join(map(str, pages))})")
        self.poll_timer.start()
        self._update_state()

    def _poll_job(self) -> None:
        for msg in self.runner.poll():
            kind = msg[0]
            if kind == "progress":
                text = tr_progress(msg[1])          # engine speaks English
                self.status(text)
                self.statusbar.set_progress(msg[2])
                self.activity.log(text)
            elif kind == "done":
                self._finish_job()
                self._on_converted(msg[1])
            elif kind == "cancelled":
                self._finish_job()
                self.notify(tr("Conversion cancelled."), "warn")
            elif kind == "error":
                self._finish_job()
                self.activity.log(str(msg[1]))
                self.notify(tr("Conversion failed. See the report for "
                               "details."), "err")

    def _finish_job(self) -> None:
        self.poll_timer.stop()
        self._busy = False
        self.statusbar.set_progress(None)
        self._update_state()

    def _on_converted(self, rep: ConversionReport) -> None:
        if rep.cancelled:
            self.notify(tr("Conversion cancelled."), "warn")
            return
        self.report_panel.show_report(rep)
        nwarn = len(rep.all_warnings())
        self.right_tabs.setTabText(2, tr("Report") + (f" ({nwarn})" if nwarn
                                                      else ""))
        if not rep.success:
            self.right_tabs.setCurrentIndex(2)
            self.notify(tr("Conversion failed. See the report for details."),
                        "err")
            return
        outputs = [p for p in rep.outputs if os.path.isfile(p)]
        self.result = {"report": rep, "outputs": outputs,
                       "dir": self._pending["dir"], "stale": False,
                       "saved": False, "options": self._pending["options"]}
        self.options_panel.set_stale(False)
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        for p in outputs:
            self.result_combo.addItem(os.path.basename(p), p)
        self.result_combo.setVisible(len(outputs) > 1)
        self.result_combo.blockSignals(False)
        self._load_result_file(0)
        self.view_tabs.setCurrentIndex(1)
        self.right_tabs.setCurrentIndex(1)
        s = rep.stats
        self.notify(tr("Converted in {s} s: {n} entities on {l} layers. "
                       "Review the result, then save it.",
                       s=f"{rep.duration_s:.1f}", n=s.total_entities(),
                       l=len(s.layers)), "ok")
        self._update_state()
        if self._pending_save:                 # DWG asked before this run
            path, self._pending_save = self._pending_save, ""
            self._save_to(path)

    def _load_result_file(self, index: int) -> None:
        if not self.result or not self.result["outputs"]:
            return
        self._result_index = index
        path = self.result["outputs"][index]
        try:
            from ..core.postprocess import layer_summary     # loads ezdxf
            rows = layer_summary(path)
        except Exception as exc:                           # pragma: no cover
            rows = []
            self.activity.log(str(exc))
        keep_edits = self.layers_panel.model.edits if index else {}
        self.layers_panel.load(rows)
        for name, ed in keep_edits.items():                # same edits for
            if name in self.layers_panel.model.edits:      # every sheet file
                self.layers_panel.model.edits[name] = ed
        self.dxf_view.load(path)
        self.dxf_view.set_hidden_layers(self.layers_panel.model.hidden_layers())

    def _on_result_file(self, index: int) -> None:
        if index >= 0:
            self._load_result_file(index)

    def _clear_result(self) -> None:
        self.result = None
        self.dxf_view.clear()
        self.layers_panel.clear()
        self.report_panel.show_report(None)
        self.right_tabs.setTabText(2, tr("Report"))
        self.result_combo.clear()
        self.result_combo.hide()
        self.options_panel.set_stale(False)

    def _mark_stale(self) -> None:
        if self.result and self.result.get("outputs"):
            self.result["stale"] = True
            self.options_panel.set_stale(True)

    def _on_options_changed(self) -> None:
        self._mark_stale()
        self._update_state()

    def _on_layer_edits(self) -> None:
        self.dxf_view.set_hidden_layers(self.layers_panel.model.hidden_layers())
        if self.result:
            self.result["saved"] = False
        self._update_state()

    # =====================================================================
    # Saving
    # =====================================================================
    def save_dxf(self) -> None:
        """Save the reviewed result as DXF or DWG (the dialog offers both;
        the format chosen in Settings > Output is proposed first)."""
        if not self.result or not self.result.get("outputs"):
            return
        outputs: List[str] = self.result["outputs"]
        stem = os.path.splitext(os.path.basename(self.pdf_path))[0]
        start_dir = self.settings.last_save_dir or os.path.dirname(self.pdf_path)
        dxf_filter = tr("DXF drawing (*.dxf)")
        dwg_filter = tr("DWG drawing, AutoCAD 2000 format (*.dwg)")
        dwg_first = self.options_panel.output_format.currentData() == "dwg"
        filters = [dwg_filter, dxf_filter] if dwg_first else \
            [dxf_filter, dwg_filter]
        title = tr("Save the drawing…")
        if len(outputs) > 1:
            pages = ", ".join(str(p) for p in
                              self.result["report"].pages_converted)
            title += "  " + tr("Sheets {pages}: one file per sheet will be "
                               "written next to this name.", pages=pages)
        ext = ".dwg" if dwg_first else ".dxf"
        path, chosen = QFileDialog.getSaveFileName(
            self, title, os.path.join(start_dir, stem + ext),
            ";;".join(filters), filters[0])
        if not path:
            return
        want_dwg = path.lower().endswith(".dwg") or (
            chosen == dwg_filter and not path.lower().endswith(".dxf"))
        path = os.path.splitext(path)[0] + (".dwg" if want_dwg else ".dxf")
        if want_dwg:
            from ..core.dwg import find_tools
            if not find_tools().available:
                QMessageBox.warning(self, APP_NAME, tr(
                    "DWG output is not available: the LibreDWG converter "
                    "(dxf2dwg) was not found next to ConvertCAD. Save as DXF, "
                    "or reinstall ConvertCAD."))
                return
            from ..core.postprocess import needs_reconversion_for_dwg
            if needs_reconversion_for_dwg(outputs[0]):
                r = QMessageBox.question(self, APP_NAME, tr(
                    "A DWG needs AutoCAD 2000 entities (classic leaders, "
                    "colour index...). ConvertCAD converts the drawing once "
                    "more for the DWG, then saves it. Continue?"))
                if r != QMessageBox.StandardButton.Yes:
                    return
                self.options_panel.output_format.setCurrentIndex(
                    self.options_panel.output_format.findData("dwg"))
                self._pending_save = path
                self.convert_or_cancel()
                return
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        """Write the result files (in the background) to `path`."""
        from ..core.postprocess import describe_edits, finalize, finalize_dwg
        outputs: List[str] = self.result["outputs"]
        want_dwg = path.lower().endswith(".dwg")
        edits = self.layers_panel.model.active_edits()
        color_mode = self.result["options"].color_mode
        note = describe_edits(edits)
        tmp_stem = os.path.splitext(os.path.basename(outputs[0]))[0]
        if len(outputs) > 1:                    # strip the _pN of sheet 1
            tmp_stem = re.sub(r"_p\d+$", "", tmp_stem)
        dst_stem = os.path.splitext(path)[0]
        log_src = os.path.join(self.result["dir"], tmp_stem + "_log.txt")
        jobs = []
        for k, src in enumerate(outputs):
            src_stem = os.path.splitext(os.path.basename(src))[0]
            suffix = src_stem[len(tmp_stem):] if len(outputs) > 1 else ""
            dst = dst_stem + suffix + (".dwg" if want_dwg else ".dxf")
            jobs.append((finalize_dwg if want_dwg else finalize,
                         (src, dst, edits, color_mode),
                         {"log_src": log_src if k == 0 else "",
                          "log_note": note}))
        self._save_thread = _SaveThread(jobs, self)
        self._save_thread.done.connect(
            lambda saved, err, p=path: self._on_saved(p, saved, err))
        self.statusbar.set_progress(-1)
        self.status(tr("Writing the DWG…") if want_dwg
                    else tr("Saving {name}…", name=os.path.basename(path)))
        self._save_thread.start()
        self._update_state()

    def _on_saved(self, path: str, saved: list, error: str) -> None:
        self._save_thread = None
        self.statusbar.set_progress(None)
        if error:
            self._update_state()
            QMessageBox.critical(self, APP_NAME,
                                 tr("Could not save the drawing: {err}",
                                    err=error))
            return
        self.result["saved"] = True
        self.settings.last_save_dir = os.path.dirname(path)
        self.settings.save()
        if len(saved) == 1:
            self.notify(tr("Saved {name}.", name=os.path.basename(saved[0])),
                        "ok")
        else:
            self.notify(tr("Saved {n} files in {folder}.", n=len(saved),
                           folder=os.path.dirname(path)), "ok")
        for p in saved:
            self.activity.log(p)
        if self.settings.open_folder_after_save:
            open_folder(saved[0])
        self._update_state()

    # =====================================================================
    # Batch, theme, language
    # =====================================================================
    def open_batch(self) -> None:
        self.options_panel.save_to_settings()
        dlg = BatchDialog(self.settings, self.options_panel.options(), self)
        dlg.exec()

    def toggle_theme(self) -> None:
        self.set_theme("light" if theme.current() == "dark" else "dark")

    def set_theme(self, name: str) -> None:
        theme.apply_theme(QApplication.instance(), name)
        self.settings.theme = name
        self.settings.save()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        for a in self.findChildren(QAction):
            if a.data() and isinstance(a.data(), str) and a.data() != "stop":
                a.setIcon(icon(a.data()))
        self.help_btn.setIcon(icon("help"))
        for w in self.findChildren(QToolButton):
            name = w.property("iconName")
            if name and w is not self.help_btn:
                w.setIcon(icon(name, theme.tok("text_muted")))
        for w in self.findChildren(QPushButton):        # e.g. report buttons
            name = w.property("iconName")
            if name:
                w.setIcon(icon(name))
        for sec in self.options_panel.sections.values():
            sec.refresh_icons()
        self.layers_panel.table.viewport().update()      # swatch colours
        self.pages_panel.apply_colors()
        self.pdf_view.apply_colors()
        self.dxf_view.apply_colors()
        if self.dxf_view.path:
            self.dxf_view.reload()
        self.report_panel.refresh()
        self._update_state()

    def set_language(self, lang: str) -> None:
        if lang != self.settings.language:
            self.settings.language = lang
            self.settings.save()
            QMessageBox.information(self, APP_NAME, tr(
                "Language changed. Restart ConvertCAD to apply it."))

    # ---- updates (opt-in) ---------------------------------------------------
    def _toggle_update_check(self, on: bool) -> None:
        self.settings.check_updates = bool(on)
        self.settings.save()

    def check_updates(self, quiet: bool = False) -> None:
        """Ask GitHub for the latest version (one request, nothing sent).
        quiet (startup check): only a newer version is shown."""
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        self._update_quiet = quiet
        self._update_thread = _UpdateThread(self)
        self._update_thread.done.connect(self._on_update_checked)
        self._update_thread.start()
        if not quiet:
            self.status(tr("Checking for updates…"))

    def _on_update_checked(self, info, error: str) -> None:
        quiet = getattr(self, "_update_quiet", False)
        if info is None:
            self.activity.log(tr("Update check failed: {e}", e=error))
            if not quiet:
                QMessageBox.warning(self, APP_NAME, tr(
                    "The latest version could not be checked: {e}.",
                    e=error))
            return
        if not info.newer:
            self.activity.log(tr("ConvertCAD is up to date ({v}).",
                                 v=info.current))
            if not quiet:
                QMessageBox.information(self, APP_NAME, tr(
                    "ConvertCAD is up to date ({v}).", v=info.current))
            return
        self.activity.log(tr("ConvertCAD {v} is available.", v=info.latest))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("ConvertCAD {v} is available (this one is {c}).",
                       v=info.latest, c=info.current))
        box.setInformativeText(tr("Nothing is installed automatically: "
                                  "download it from its release page."))
        go = box.addButton(tr("Open the release page"),
                           QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(info.url))

    def _fill_recent(self, menu: QMenu = None) -> None:
        menu = menu or self.recent_menu
        menu.clear()
        recent = self.settings.existing_recent()
        if not recent:
            a = menu.addAction(tr("No recent file"))
            a.setEnabled(False)
        for p in recent:
            menu.addAction(os.path.basename(p),
                           lambda path=p: self.open_pdf(path)).setToolTip(p)
        if recent:
            menu.addSeparator()
            menu.addAction(tr("Clear the list"), self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings.recent_files = []
        self.settings.save()
        self.empty.set_recent([])

    # =====================================================================
    # Window events
    # =====================================================================
    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
            event.acceptProposedAction()
            self.empty.set_drag_active(True)

    def dragLeaveEvent(self, event) -> None:
        self.empty.set_drag_active(False)

    def dropEvent(self, event) -> None:
        self.empty.set_drag_active(False)
        urls = event.mimeData().urls()
        if urls:
            self.open_pdf(urls[0].toLocalFile())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast._place()
        self._fit_toolbar()

    def _fit_toolbar(self) -> None:
        """Tool labels shown when they fit; otherwise the tools show their
        icon only (their name stays in the tooltip). German or Spanish
        labels are longer than English ones."""
        buttons = getattr(self, "_compact_buttons", [])
        if not buttons:
            return
        beside = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in buttons:
            b.setToolButtonStyle(beside)
        need = sum(w.sizeHint().width() for w in self.toolbar.findChildren(
            QToolButton) if w.objectName() != "qt_toolbar_ext_button") + 120
        if need > self.width():
            for b in buttons:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def open_ocr_models(self) -> None:
        """Settings > Scanned pages > OCR languages and models…"""
        dlg = OcrModelsDialog(self)
        dlg.models_changed.connect(self.options_panel.refresh_ocr)
        dlg.exec()
        self.options_panel.refresh_ocr()

    def closeEvent(self, event) -> None:
        if self._save_thread is not None:
            self._save_thread.wait(60000)            # let the save finish
        if self._busy:
            r = QMessageBox.question(self, APP_NAME, tr(
                "The conversion is still running. Quit anyway?"))
            if r != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        elif not self._confirm_discard("The result has not been saved. Quit "
                                       "anyway?"):
            event.ignore()
            return
        self.runner.shutdown()
        stop_downloads()                             # OCR model downloads
        self.options_panel.save_to_settings()
        self.settings.window_geometry = bytes(
            self.saveGeometry().toBase64()).decode()
        self.settings.window_state = ",".join(
            str(x) for x in self.main_split.sizes() + self.center_split.sizes())
        self.settings.show_activity = self.a_show_activity.isChecked()
        self.settings.save()
        if self.doc is not None:
            self.doc.close()
        shutil.rmtree(self.temp_root, ignore_errors=True)
        event.accept()
