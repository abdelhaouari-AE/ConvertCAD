"""
pages_panel.py — the sheet list on the left.

One row per PDF page: thumbnail, a checkbox to include it in the
conversion, the sheet number, its kind (Vector / Scan / Empty), paper size
and rotation. Thumbnails are rendered one at a time on a timer so opening a
50-page set never freezes the window.
"""

from typing import TYPE_CHECKING, List

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMenu,
                               QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr, tr_paper
from . import theme
from .widgets import PanelHeader, label, small_button

if TYPE_CHECKING:                          # typing only: no PyMuPDF at start
    from ..core.pdfinfo import PageInfo

THUMB_W = 150


class _SheetRow(QWidget):
    toggled = Signal()

    def __init__(self, info: "PageInfo", parent=None):
        super().__init__(parent)
        self.info = info
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, int(THUMB_W * 0.72))
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.check = QCheckBox(f"{tr('Sheet')} {info.number}")
        self.check.setChecked(info.kind != "empty")
        self.check.setToolTip(tr("Include this sheet in the conversion"))
        self.check.toggled.connect(self.toggled.emit)
        top.addWidget(self.check)
        top.addStretch(1)
        kind = {"vector": tr("Vector"), "scanned": tr("Scan"),
                "empty": tr("Empty")}.get(info.kind, info.kind)
        self.chip = QLabel(kind)
        self.chip.setToolTip({
            "vector": tr("Vector drawing: converted to exact CAD entities."),
            "scanned": tr("Scanned sheet: traced and read with OCR."),
            "empty": tr("No drawing content on this sheet.")}.get(info.kind, ""))
        top.addWidget(self.chip)
        lay.addLayout(top)
        meta = tr_paper(info.paper)
        if info.rotation:
            meta += "   " + tr("Rotated {deg}°", deg=info.rotation)
        lay.addWidget(label(meta, "caption"))
        self.apply_colors()

    def apply_colors(self) -> None:
        """(Re)apply theme colours — called again when the theme changes."""
        self.thumb.setStyleSheet(f"background:{theme.tok('input')};"
                                 f"border:1px solid {theme.tok('border')};")
        color = {"vector": theme.tok("ok"), "scanned": theme.tok("warn"),
                 "empty": theme.tok("text_faint")}.get(self.info.kind,
                                                       theme.tok("text_faint"))
        self.chip.setStyleSheet(f"color:{color}; border:1px solid {color};"
                                f"border-radius:3px; padding:0 5px;"
                                f"font-size:7.5pt; font-weight:600;")

    def set_thumbnail(self, pm: QPixmap) -> None:
        self.thumb.setPixmap(pm.scaled(self.thumb.size() - QSize(6, 6),
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))


class PagesPanel(QFrame):
    page_activated = Signal(int)          # 0-based page index
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.doc = None
        self._rows: List[_SheetRow] = []
        self._pending: List[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._render_next)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # Selection actions live in a compact menu in the panel header: they
        # take no room in this narrow panel and fit any language.
        self.select_btn = small_button("select", tr("Select sheets"))
        self.select_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.select_btn)
        for text, mode in ((tr("Select all"), "all"),
                           (tr("Select none"), "none"),
                           (tr("Vector sheets only"), "vector"),
                           (tr("Scanned sheets only"), "scanned"),
                           (tr("Invert selection"), "invert")):
            menu.addAction(text, lambda m=mode: self._select(m))
        self.select_btn.setMenu(menu)
        self.select_btn.setStyleSheet("QToolButton::menu-indicator{image:none;}")
        self.select_btn.hide()
        self.header = PanelHeader(tr("Sheets"), [self.select_btn])
        lay.addWidget(self.header)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list, 1)
        self.summary = label("", "caption")
        self.summary.setContentsMargins(10, 4, 10, 6)
        lay.addWidget(self.summary)
        self.setMinimumWidth(THUMB_W + 40)

    # ------------------------------------------------------------------------
    def load(self, doc, infos: List["PageInfo"]) -> None:
        self.doc = doc
        self.list.clear()
        self._rows = []
        for info in infos:
            row = _SheetRow(info)
            row.toggled.connect(self._changed)
            item = QListWidgetItem(self.list)
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
            self._rows.append(row)
        self._pending = list(range(len(infos)))
        self._timer.start()
        self.select_btn.setVisible(len(infos) > 1)
        if infos:
            self.list.setCurrentRow(0)
        self._changed()

    def clear(self) -> None:
        self._timer.stop()
        self.doc = None
        self.list.clear()
        self._rows = []
        self.summary.setText("")
        self.select_btn.hide()

    def _render_next(self) -> None:
        from ..core.compat import pymupdf
        if not self._pending or self.doc is None:
            self._timer.stop()
            return
        i = self._pending.pop(0)
        try:
            page = self.doc[i]
            z = (THUMB_W * 2) / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            self._rows[i].set_thumbnail(QPixmap.fromImage(img))
        except Exception:                                  # pragma: no cover
            pass

    def _on_row(self, row: int) -> None:
        if row >= 0:
            self.page_activated.emit(row)

    def set_current(self, index: int) -> None:
        if 0 <= index < self.list.count() and self.list.currentRow() != index:
            self.list.blockSignals(True)
            self.list.setCurrentRow(index)
            self.list.blockSignals(False)

    def _select(self, mode: str) -> None:
        """mode: all | none | vector | scanned | invert"""
        for r in self._rows:
            if mode == "invert":
                state = not r.check.isChecked()
            else:
                state = (mode == "all"
                         or (mode == "vector" and r.info.kind == "vector")
                         or (mode == "scanned" and r.info.kind == "scanned"))
            r.check.blockSignals(True)
            r.check.setChecked(state)
            r.check.blockSignals(False)
        self._changed()

    def _changed(self) -> None:
        n = len(self.selected_pages())
        self.summary.setText(tr("{n} of {total} sheets selected", n=n,
                                total=len(self._rows)))
        self.selection_changed.emit()

    def apply_colors(self) -> None:
        for r in self._rows:
            r.apply_colors()

    def selected_pages(self) -> List[int]:
        """1-based page numbers checked for conversion."""
        return [r.info.number for r in self._rows if r.check.isChecked()]

    def page_count(self) -> int:
        return len(self._rows)
