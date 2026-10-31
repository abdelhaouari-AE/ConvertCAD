"""
theme.py — colour tokens and the Qt style sheet (dark and light).

Design intent
-------------
* The drawing is the hero: the chrome is quiet graphite (dark) or cool
  drafting-film grey (light); colour is reserved for actions and markup.
* Brand teal (shared with the author's other tools) marks the ONE primary
  action of the moment.
* Markup drawn ON the sheet (snap glyphs, measurements, calibration) uses
  its own fixed palette, readable on white paper and on dark canvas alike.

Every colour of the interface comes from TOKENS below — change a value
here and the whole application follows.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "dark": {
        "bg": "#1D2228", "panel": "#232930", "panel_alt": "#2B323B",
        "input": "#1A1F25", "canvas": "#15191E", "sheet_shadow": "#0C0F12",
        "border": "#343C46", "border_strong": "#4A5460",
        "text": "#E4E8EC", "text_muted": "#9BA5B1", "text_faint": "#6E7884",
        "accent": "#2BB3C0", "accent_hover": "#45C5D1",
        "accent_press": "#1F9AA6", "on_accent": "#04262A",
        "ok": "#59C08A", "warn": "#E3A33E", "err": "#EE6A5A",
        "model_space": "#212830", "selection": "#2BB3C0",
    },
    "light": {
        "bg": "#E9EDF0", "panel": "#F7F8F9", "panel_alt": "#E3E8EC",
        "input": "#FFFFFF", "canvas": "#C9D0D6", "sheet_shadow": "#9AA4AD",
        "border": "#CBD2D8", "border_strong": "#A9B3BC",
        "text": "#1B232B", "text_muted": "#55606C", "text_faint": "#89939E",
        "accent": "#0E7490", "accent_hover": "#0B6178",
        "accent_press": "#094F62", "on_accent": "#FFFFFF",
        "ok": "#1D8A57", "warn": "#B26A00", "err": "#C23A2B",
        "model_space": "#212830", "selection": "#2BB3C0",
    },
}

# Markup drawn on the sheet: identical in both themes (paper is white).
MARKUP = {
    "snap": "#F08A24",          # object-snap glyphs (CAD orange)
    "measure": "#1D8FE1",       # measurement dimensions
    "calibrate": "#C026D3",     # calibration line
    "area": "#0E9F6E",          # selected area frame
    "halo": "#FFFFFF",          # label background on the sheet
}

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter",
                 "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo",
                 "Courier New"]

_current = "dark"


def current() -> str:
    return _current


def tok(name: str) -> str:
    return TOKENS[_current][name]


def qcolor(name: str) -> QColor:
    return QColor(TOKENS[_current].get(name, MARKUP.get(name, "#FF00FF")))


def ui_font(point_size: float = 9.0, weight: int = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(point_size)
    f.setWeight(QFont.Weight(weight))
    f.setStyleHint(QFont.StyleHint.SansSerif)
    return f


def mono_font(point_size: float = 8.5) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setPointSizeF(point_size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def apply_theme(app: QApplication, name: str) -> None:
    """Apply palette + style sheet. Safe to call again to switch theme."""
    global _current
    _current = name if name in TOKENS else "dark"
    t = TOKENS[_current]
    app.setStyle("Fusion")
    app.setFont(ui_font(9.0))
    pal = QPalette()
    role = QPalette.ColorRole
    pal.setColor(role.Window, QColor(t["bg"]))
    pal.setColor(role.WindowText, QColor(t["text"]))
    pal.setColor(role.Base, QColor(t["input"]))
    pal.setColor(role.AlternateBase, QColor(t["panel_alt"]))
    pal.setColor(role.Text, QColor(t["text"]))
    pal.setColor(role.Button, QColor(t["panel_alt"]))
    pal.setColor(role.ButtonText, QColor(t["text"]))
    pal.setColor(role.Highlight, QColor(t["accent"]))
    pal.setColor(role.HighlightedText, QColor(t["on_accent"]))
    pal.setColor(role.ToolTipBase, QColor(t["panel_alt"]))
    pal.setColor(role.ToolTipText, QColor(t["text"]))
    pal.setColor(role.PlaceholderText, QColor(t["text_faint"]))
    pal.setColor(role.Link, QColor(t["accent"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.Text, QColor(t["text_faint"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.ButtonText,
                 QColor(t["text_faint"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.WindowText,
                 QColor(t["text_faint"]))
    app.setPalette(pal)
    from ..config import settings_dir
    from .icons import clear_cache, write_check_svg
    clear_cache()                       # icons are tinted with the theme
    check = write_check_svg(settings_dir() + "/icons", t["on_accent"])
    app.setStyleSheet(style_sheet(t, check))


def style_sheet(t: dict, check_path: str = "") -> str:
    """The application style sheet, built from tokens."""
    return f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {t['bg']}; }}
QWidget {{ color: {t['text']}; }}
QToolTip {{
    background: {t['panel_alt']}; color: {t['text']};
    border: 1px solid {t['border_strong']}; padding: 5px 7px;
}}

/* ---- menus -------------------------------------------------------- */
QMenuBar {{ background: {t['bg']}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 9px; border-radius: 3px; background: transparent; }}
QMenuBar::item:selected {{ background: {t['panel_alt']}; }}
QMenu {{
    background: {t['panel']}; border: 1px solid {t['border_strong']};
    padding: 4px;
}}
QMenu::item {{ padding: 5px 26px 5px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background: {t['panel_alt']}; }}
QMenu::item:disabled {{ color: {t['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 4px; }}

/* ---- command bar -------------------------------------------------- */
QToolBar#CommandBar {{
    background: {t['panel']}; border: 0;
    border-bottom: 1px solid {t['border']}; padding: 4px 6px; spacing: 2px;
}}
QToolBar#CommandBar::separator {{
    background: {t['border']}; width: 1px; margin: 6px 6px;
}}
QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 4px;
    padding: 4px 8px; color: {t['text']};
}}
QToolButton:hover {{ background: {t['panel_alt']}; border-color: {t['border']}; }}
QToolButton:pressed {{ background: {t['border']}; }}
QToolButton:checked {{
    background: {t['panel_alt']}; border-color: {t['accent']}; color: {t['text']};
}}
QToolButton:disabled {{ color: {t['text_faint']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---- buttons ------------------------------------------------------- */
QPushButton {{
    background: {t['panel_alt']}; color: {t['text']};
    border: 1px solid {t['border_strong']}; border-radius: 4px;
    padding: 5px 12px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {t['text_faint']}; }}
QPushButton:pressed {{ background: {t['border']}; }}
QPushButton:disabled {{ color: {t['text_faint']}; border-color: {t['border']}; }}
QPushButton:focus {{ border-color: {t['accent']}; }}
QPushButton[kind="primary"], QToolButton[kind="primary"] {{
    background: {t['accent']}; color: {t['on_accent']};
    border: 1px solid {t['accent']}; font-weight: 600;
}}
QPushButton[kind="primary"]:hover, QToolButton[kind="primary"]:hover {{
    background: {t['accent_hover']}; border-color: {t['accent_hover']};
}}
QPushButton[kind="primary"]:pressed, QToolButton[kind="primary"]:pressed {{
    background: {t['accent_press']};
}}
QPushButton[kind="primary"]:disabled, QToolButton[kind="primary"]:disabled {{
    background: {t['panel_alt']}; color: {t['text_faint']};
    border-color: {t['border']};
}}
QPushButton[kind="danger"], QToolButton[kind="danger"] {{
    background: transparent; color: {t['err']}; border: 1px solid {t['err']};
}}
QPushButton[kind="link"] {{
    background: transparent; border: 0; color: {t['accent']}; padding: 2px 0;
    text-align: left;
}}
QPushButton[kind="link"]:hover {{ text-decoration: underline; }}
QPushButton[kind="chip"] {{
    background: transparent; border: 1px solid {t['border']};
    border-radius: 3px; padding: 2px 8px; color: {t['text_muted']};
}}
QPushButton[kind="chip"]:hover {{ color: {t['text']}; border-color: {t['border_strong']}; }}

/* ---- inputs -------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {t['input']}; border: 1px solid {t['border']};
    border-radius: 4px; padding: 3px 6px; min-height: 18px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t['accent']};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled {{ color: {t['text_faint']}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {t['panel']}; border: 1px solid {t['border_strong']};
    selection-background-color: {t['panel_alt']}; selection-color: {t['text']};
    padding: 2px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: 0; }}
QCheckBox, QRadioButton {{ spacing: 7px; padding: 2px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator {{
    border: 1px solid {t['border_strong']}; border-radius: 3px;
    background: {t['input']};
}}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{
    background: {t['accent']}; border-color: {t['accent']};
    image: url("{check_path}");
}}
QCheckBox:disabled {{ color: {t['text_faint']}; }}

/* ---- panels, tabs --------------------------------------------------- */
QFrame#Panel, QWidget#Panel {{ background: {t['panel']}; }}
QFrame#PanelHeader {{
    background: {t['panel']}; border-bottom: 1px solid {t['border']};
}}
QLabel#PanelTitle {{ font-weight: 600; font-size: 9.5pt; }}
QLabel[role="muted"] {{ color: {t['text_muted']}; }}
QLabel[role="faint"] {{ color: {t['text_faint']}; }}
QLabel[role="caption"] {{ color: {t['text_faint']}; font-size: 8pt; }}
QLabel[role="ok"] {{ color: {t['ok']}; }}
QLabel[role="warn"] {{ color: {t['warn']}; }}
QLabel[role="err"] {{ color: {t['err']}; }}
QLabel[role="title"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[role="notice"] {{
    background: {t['panel_alt']}; border-left: 3px solid {t['warn']};
    padding: 6px 8px; color: {t['text']};
}}
QTabWidget::pane {{ border: 0; background: {t['panel']}; }}
QTabBar {{ background: {t['panel']}; }}
QTabBar::tab {{
    background: transparent; color: {t['text_muted']};
    padding: 7px 12px 6px 12px; border: 0; border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom-color: {t['accent']}; }}
QTabBar::tab:disabled {{ color: {t['text_faint']}; }}

/* ---- collapsible sections ---------------------------------------- */
QToolButton#SectionHeader {{
    background: transparent; border: 0; border-radius: 0;
    border-top: 1px solid {t['border']}; padding: 8px 4px 8px 2px;
    font-weight: 600; text-align: left; color: {t['text']};
}}
QToolButton#SectionHeader:hover {{ background: {t['panel_alt']}; }}

/* ---- lists, tables, text ------------------------------------------- */
QListWidget, QTableView, QTreeView {{
    background: {t['panel']}; border: 0; alternate-background-color: {t['panel_alt']};
    selection-background-color: {t['panel_alt']}; selection-color: {t['text']};
}}
QListWidget::item {{ border-radius: 4px; }}
QListWidget::item:selected {{ background: {t['panel_alt']}; }}
QHeaderView::section {{
    background: {t['panel']}; color: {t['text_muted']}; border: 0;
    border-bottom: 1px solid {t['border']}; padding: 4px 6px; font-weight: 500;
}}
QTableView {{ gridline-color: transparent; }}
QTableView::item {{ padding: 2px 4px; }}
QTextBrowser, QPlainTextEdit, QTextEdit {{
    background: {t['panel']}; border: 0; selection-background-color: {t['accent']};
    selection-color: {t['on_accent']};
}}
QPlainTextEdit#Activity {{ background: {t['input']}; color: {t['text_muted']}; }}

/* ---- scrollbars, splitters, progress ------------------------------ */
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {t['border_strong']}; border-radius: 4px;
    min-height: 28px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {t['text_faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QProgressBar {{
    background: {t['input']}; border: 1px solid {t['border']}; border-radius: 3px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}

/* ---- title-block status bar --------------------------------------- */
QFrame#TitleBlock {{ background: {t['panel']}; border-top: 1px solid {t['border_strong']}; }}
QFrame#TBCell {{ border-right: 1px solid {t['border']}; }}
QLabel#TBCaption {{ color: {t['text_faint']}; font-size: 7.5pt; }}
QLabel#TBValue {{ color: {t['text']}; }}
QToolButton#SnapToggle {{
    padding: 0px 5px; border: 1px solid {t['border']}; border-radius: 3px;
    color: {t['text_faint']}; font-size: 7.5pt; font-weight: 600;
}}
QToolButton#SnapToggle:checked {{
    color: {t['text']}; border-color: {MARKUP['snap']}; background: transparent;
}}

/* ---- empty state ---------------------------------------------------- */
QWidget#EmptyState {{ background: {t['canvas']}; }}
QFrame#DropCard {{
    background: {t['panel']}; border: 1px dashed {t['border_strong']};
    border-radius: 6px;
}}
QFrame#DropCard[drag="true"] {{ border: 2px dashed {t['accent']}; }}
QLabel#StepNumber {{
    color: {t['accent']}; font-weight: 700; font-size: 10pt;
    border: 1px solid {t['accent']}; border-radius: 10px;
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
    qproperty-alignment: AlignCenter;
}}

/* ---- toast ----------------------------------------------------------- */
QLabel#Toast {{
    background: {t['panel_alt']}; color: {t['text']};
    border: 1px solid {t['border_strong']}; border-left: 3px solid {t['accent']};
    border-radius: 4px; padding: 8px 12px;
}}
QLabel#Toast[level="warn"] {{ border-left-color: {t['warn']}; }}
QLabel#Toast[level="err"] {{ border-left-color: {t['err']}; }}
QLabel#Toast[level="ok"] {{ border-left-color: {t['ok']}; }}
"""
