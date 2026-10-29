"""
layers_panel.py — review and adjust the layers of the converted DXF.

Before saving, the user can:
  * untick a layer  -> hidden in the DXF preview AND removed from the file
  * rename a layer  -> double-click its name (e.g. GEO_GRAY_025_CENTER -> AXES)
  * recolour it     -> click its colour swatch
Edits are applied when the DXF is saved (core/postprocess.py), so the
temporary conversion result is never modified.
"""

from functools import lru_cache
from typing import Dict, List

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRect, QSize,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QPainter,
                           QPalette, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QColorDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLineEdit,
                               QPushButton, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QTableView, QVBoxLayout, QWidget)

from ..core.layers import sanitize
from ..core.layer_edits import PROTECTED_LAYERS, LayerEdit, LayerRow
from ..i18n import tr
from . import theme
from .widgets import label, small_button

COL_KEEP, COL_COLOR, COL_NAME, COL_COUNT = range(4)
LINETYPE_ROLE = Qt.ItemDataRole.UserRole + 1     # caption under the name
ROW_HEIGHT = 36                                  # two lines: name + linetype


def swatch_icon(rgb, size: int = 14) -> QIcon:
    """Colour swatch with a thin border, so white/pale layers stay visible.

    Like CAD software, colour 7 (white) is shown black on a light theme:
    it is the 'black/white' colour that always contrasts with the background.
    """
    r, g, b = (int(c) for c in rgb[:3])
    return _swatch(r, g, b, theme.current(), size)


@lru_cache(maxsize=256)
def _swatch(r: int, g: int, b: int, theme_name: str, size: int) -> QIcon:
    if theme_name == "light" and min(r, g, b) >= 245:
        r = g = b = 0
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setPen(QColor(theme.TOKENS[theme_name]["border_strong"]))
    p.setBrush(QColor(r, g, b))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


def linetype_label(name: str) -> str:
    """AutoCAD shows the default linetype as 'Continuous', others in capitals."""
    return "Continuous" if (name or "").upper() == "CONTINUOUS" else (name or "")


class LayerModel(QAbstractTableModel):
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[LayerRow] = []
        self.edits: Dict[str, LayerEdit] = {}

    def load(self, rows: List[LayerRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.edits = {r.name: LayerEdit() for r in rows}
        self.endResetModel()

    # ---- Qt model API ---------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and \
                role == Qt.ItemDataRole.DisplayRole:
            return ["", "", tr("Layer") + "  ·  " + tr("Linetype"),
                    tr("Entities")][section]
        if orientation == Qt.Orientation.Horizontal and \
                role == Qt.ItemDataRole.ToolTipRole and section == COL_KEEP:
            return tr("Keep")
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        name = self.rows[index.row()].name
        protected = name.upper() in PROTECTED_LAYERS
        if index.column() == COL_KEEP and not protected:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == COL_NAME and not protected:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[index.row()]
        ed = self.edits[r.name]
        col = index.column()
        if col == COL_KEEP and role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if ed.keep else Qt.CheckState.Unchecked
        if col == COL_COLOR:
            rgb = ed.color or r.rgb
            if role == Qt.ItemDataRole.DecorationRole:
                return swatch_icon(rgb)
            if role == Qt.ItemDataRole.ToolTipRole:
                return tr("Layer colour") + f"  #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        if col == COL_NAME:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return ed.new_name or r.name
            if role == Qt.ItemDataRole.FontRole and (ed.new_name or not ed.keep):
                f = QFont()
                f.setItalic(bool(ed.new_name))
                f.setStrikeOut(not ed.keep)
                return f
            if role == LINETYPE_ROLE:
                return linetype_label(r.linetype)
            if role == Qt.ItemDataRole.ToolTipRole:
                tip = f"{ed.new_name or r.name}\n{tr('Linetype')}: " \
                      f"{linetype_label(r.linetype)}"
                if ed.new_name:
                    tip += f"\n({tr('was')} {r.name})"
                return tip
            if role == Qt.ItemDataRole.ForegroundRole and not ed.keep:
                return QColor(theme.tok("text_faint"))
            if role == Qt.ItemDataRole.UserRole:        # sort by name
                return (ed.new_name or r.name).upper()
        if col == COL_COUNT:
            if role == Qt.ItemDataRole.DisplayRole:
                return f"{r.count:,}".replace(",", " ")
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            if role == Qt.ItemDataRole.UserRole:
                return r.count
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        r = self.rows[index.row()]
        ed = self.edits[r.name]
        if index.column() == COL_KEEP and role == Qt.ItemDataRole.CheckStateRole:
            ed.keep = Qt.CheckState(value) == Qt.CheckState.Checked
        elif index.column() == COL_NAME and role == Qt.ItemDataRole.EditRole:
            new = sanitize(str(value).strip()) if str(value).strip() else ""
            ed.new_name = "" if new == r.name else new
        else:
            return False
        self.dataChanged.emit(self.index(index.row(), 0),
                              self.index(index.row(), COL_COUNT))
        self.edited.emit()
        return True

    # ---- helpers ------------------------------------------------------------------
    def set_color(self, row: int, rgb) -> None:
        self.edits[self.rows[row].name].color = tuple(rgb)
        self.dataChanged.emit(self.index(row, COL_COLOR),
                              self.index(row, COL_COLOR))
        self.edited.emit()

    def set_all(self, keep: bool) -> None:
        for r in self.rows:
            if r.name.upper() not in PROTECTED_LAYERS:
                self.edits[r.name].keep = keep
        self.dataChanged.emit(self.index(0, 0),
                              self.index(len(self.rows) - 1, COL_COUNT))
        self.edited.emit()

    def reset(self) -> None:
        self.load(self.rows)
        self.edited.emit()

    def hidden_layers(self) -> set:
        return {n for n, e in self.edits.items() if not e.keep}

    def active_edits(self) -> Dict[str, LayerEdit]:
        return {n: e for n, e in self.edits.items()
                if not e.keep or e.new_name or e.color is not None}


class NameDelegate(QStyledItemDelegate):
    """Paints the layer name with its linetype as a small caption below.

    Two lines per row leave the whole width of the panel to the name, which
    is the information the user actually reads (GEO_BLACK_050_CENTER is long),
    instead of squeezing it between a Linetype and an Entities column.
    Long names are elided in the middle so the meaningful suffix stays visible.
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name, opt.text = opt.text, ""                 # background/selection only
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter,
                          opt.widget)
        rect = option.rect.adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        # line 1 — the name (italic when renamed, struck out when removed)
        font = QFont(opt.font)
        fm = QFontMetrics(font)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if selected:
            pen = option.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            pen = QColor(fg) if fg is not None else \
                option.palette.color(QPalette.ColorRole.Text)
        painter.setFont(font)
        painter.setPen(pen)
        top = QRect(rect.left(), rect.top(), rect.width(), fm.height())
        painter.drawText(top, int(Qt.AlignmentFlag.AlignLeft
                                  | Qt.AlignmentFlag.AlignVCenter),
                         fm.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                       rect.width()))
        # line 2 — the linetype, small and muted
        small = QFont(opt.font)
        if small.pointSizeF() > 0:
            small.setPointSizeF(small.pointSizeF() * 0.85)
        else:
            small.setPixelSize(max(8, int(small.pixelSize() * 0.85)))
        small.setStrikeOut(False)
        small.setItalic(False)
        sfm = QFontMetrics(small)
        painter.setFont(small)
        painter.setPen(QColor(theme.tok("text_faint")))
        bottom = QRect(rect.left(), top.bottom() + 1, rect.width(),
                       sfm.height())
        lt = index.data(LINETYPE_ROLE) or ""
        painter.drawText(bottom, int(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignVCenter),
                         sfm.elidedText(lt, Qt.TextElideMode.ElideRight,
                                        rect.width()))
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), ROW_HEIGHT)

    def updateEditorGeometry(self, editor, option, index):
        # rename box over the first line only, the caption stays visible
        r = option.rect
        editor.setGeometry(QRect(r.left() + 2, r.top() + 2, r.width() - 4,
                                 min(r.height() - 4, 22)))


class LayersPanel(QFrame):
    edits_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.model = LayerModel(self)
        self.model.edited.connect(self.edits_changed.emit)
        self.model.edited.connect(lambda: self._update_summary())
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(COL_NAME)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        empty = label(tr("Convert a drawing to review its layers here."),
                      "muted", wrap=True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setContentsMargins(20, 20, 20, 20)
        self.stack.addWidget(empty)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Filter layers"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        top.addWidget(self.filter, 1)
        self.btn_reset = small_button("reset", tr("Undo all layer changes"))
        self.btn_reset.clicked.connect(self.model.reset)
        top.addWidget(self.btn_reset)
        pl.addLayout(top)
        btns = QHBoxLayout()
        btns.setSpacing(4)
        for text, fn in ((tr("Show all"), lambda: self.model.set_all(True)),
                         (tr("Hide all"), lambda: self.model.set_all(False))):
            b = QPushButton(text)
            b.setProperty("kind", "chip")
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        self.summary = label("", "caption")
        btns.addWidget(self.summary)
        pl.addLayout(btns)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setItemDelegateForColumn(COL_NAME, NameDelegate(self.table))
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(24)
        hh.setSectionResizeMode(COL_KEEP, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(COL_KEEP, 30)
        hh.setSectionResizeMode(COL_COLOR, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(COL_COLOR, 26)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_COUNT, QHeaderView.ResizeMode.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.clicked.connect(self._on_click)
        pl.addWidget(self.table, 1)
        pl.addWidget(label(tr("Unchecked layers are hidden here and removed "
                              "from the saved DXF. Double-click a name to "
                              "rename it, click a colour to change it."),
                           "caption", wrap=True))
        self.stack.addWidget(page)
        lay.addWidget(self.stack)

    def load(self, rows: List[LayerRow]) -> None:
        self.model.load(rows)
        self.table.sortByColumn(COL_COUNT, Qt.SortOrder.DescendingOrder)
        self.stack.setCurrentIndex(1 if rows else 0)
        self._update_summary()

    def _update_summary(self) -> None:
        total = len(self.model.rows)
        kept = total - len(self.model.hidden_layers())
        self.summary.setText(tr("{kept} of {total} layers kept", kept=kept,
                                total=total))

    def clear(self) -> None:
        self.model.load([])
        self.stack.setCurrentIndex(0)

    def _on_click(self, index) -> None:
        src = self.proxy.mapToSource(index)
        if src.column() != COL_COLOR:
            return
        row = self.model.rows[src.row()]
        ed = self.model.edits[row.name]
        c = QColorDialog.getColor(QColor(*(ed.color or row.rgb)), self,
                                  tr("Layer colour"))
        if c.isValid():
            self.model.set_color(src.row(), (c.red(), c.green(), c.blue()))
