"""Thème visuel : palette claire imposée (indépendante du mode sombre de Windows),
feuille de style, icônes vectorielles et couleurs de catégories."""

import os
import tempfile

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

# ------------------------------------------------------------------ couleurs
BG = "#F5F6FA"
SURFACE = "#FFFFFF"
BORDER = "#E4E7EC"
BORDER_STRONG = "#D0D5DD"
TEXT = "#101828"
MUTED = "#667085"
SUBTLE = "#98A2B3"
ACCENT = "#4F46E5"
ACCENT_HOVER = "#4338CA"
ACCENT_SOFT = "#EEF0FE"
HOVER = "#F2F4F7"
SECTION = "#F2F4F7"
TOTAL = "#F8F9FC"
GREEN = "#067647"
GREEN_SOFT = "#ECFDF3"
RED = "#B42318"
RED_SOFT = "#FEF3F2"
ORANGE = "#B54708"
ORANGE_SOFT = "#FFFAEB"
BLUE = "#175CD3"
BLUE_SOFT = "#EFF8FF"

CATEGORY_PALETTE = ["#4F46E5", "#0E9384", "#DD2590", "#DC6803", "#2E90FA", "#7A5AF8", "#12B76A", "#F04438",
                    "#6172F3", "#E04F16", "#15B79E", "#9E77ED", "#F79009", "#0BA5EC", "#D444F1", "#66C61C"]
CHART_COLORS = CATEGORY_PALETTE


def category_color(db, cat_id):
    """Couleur stable d'une catégorie (celle de sa catégorie principale)."""
    if cat_id is None:
        return QColor(SUBTLE)
    top = db.top_category_id(cat_id)
    if top is None:
        return QColor(SUBTLE)
    return QColor(CATEGORY_PALETTE[top % len(CATEGORY_PALETTE)])


def soft(color, alpha=28):
    c = QColor(color)
    c.setAlpha(alpha)
    return c


# -------------------------------------------------------------------- icônes
_ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/>'
            '<circle cx="3.5" cy="18" r="1"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
    "compare": '<path d="M7 4v16M7 4l-3 3M7 4l3 3M17 20V4M17 20l-3-3M17 20l3-3"/>',
    "pie": '<path d="M21.2 15.9A10 10 0 1 1 8 2.8"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M8 17v-5M13 17V8M18 17v-9"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "tag": '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/>'
           '<circle cx="7" cy="7" r="1.2"/>',
    "wand": '<path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8L19 13M17.8 6.2L19 5M3 21l9-9M12.2 6.2L11 5"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "undo": '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
    "sparkle": '<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "x": '<path d="M18 6L6 18M6 6l12 12"/>',
    "scale": '<path d="M12 3v18M7 21h10M5 7h14"/><path d="M5 7l-3 7a3.5 3.5 0 0 0 6 0zM19 7l-3 7a3.5 3.5 0 0 0 6 0z"/>',
}


def _svg(name, color, width=2.0):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>')


def pixmap(name, color=MUTED, size=18):
    renderer = QSvgRenderer(QByteArray(_svg(name, color).encode()))
    pm = QPixmap(QSize(size * 2, size * 2))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


def icon(name, color=MUTED, active_color=None, size=18):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Active, QIcon.On)
    ic.addPixmap(pixmap(name, SUBTLE, size), QIcon.Disabled, QIcon.Off)
    return ic


# --------------------------------------------------------------- application
def _write_asset(name, content):
    folder = os.path.join(tempfile.gettempdir(), "mescomptes-theme")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path.replace("\\", "/")


def stylesheet():
    chevron = _write_asset("chevron.svg", _svg("chevron", MUTED, 2.2))
    check = _write_asset("check.svg", _svg("check", "#FFFFFF", 3))
    return f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, QWidget#page {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 17pt; font-weight: 700; color: {TEXT}; }}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#kpiLabel {{ color: {MUTED}; font-size: 9pt; font-weight: 600; }}
QLabel#kpiValue {{ font-size: 18pt; font-weight: 700; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; color: {TEXT}; }}
QLabel#navSection {{ color: {SUBTLE}; font-size: 8pt; font-weight: 700; padding: 10px 12px 4px 12px; }}

QFrame#sidebar {{ background: {SURFACE}; border: none; border-right: 1px solid {BORDER}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#drawer {{ background: {SURFACE}; border: none; border-left: 1px solid {BORDER}; }}
QFrame#banner {{ background: {ORANGE_SOFT}; border: 1px solid #FEDF89; border-radius: 10px; }}
QFrame#hline {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
              padding: 6px 12px; color: {TEXT}; font-weight: 500; }}
QPushButton:hover {{ background: #F9FAFB; }}
QPushButton:pressed {{ background: {HOVER}; }}
QPushButton:disabled {{ color: {SUBTLE}; background: #FAFAFB; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #C7C9F9; border-color: #C7C9F9; color: white; }}
QPushButton#danger {{ color: {RED}; }}
QPushButton#ghost {{ border: none; background: transparent; color: {MUTED}; }}
QPushButton#ghost:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px 4px; font-weight: 600; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#nav {{ border: none; background: transparent; text-align: left; padding: 8px 12px;
                  border-radius: 8px; color: #344054; font-weight: 500; }}
QPushButton#nav:hover {{ background: {HOVER}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}
QPushButton#chip {{ border: 1px solid {BORDER_STRONG}; border-radius: 12px; padding: 4px 12px;
                   background: {SURFACE}; color: #344054; }}
QPushButton#chip:checked {{ background: {ACCENT_SOFT}; border-color: #C7CBFB; color: {ACCENT}; font-weight: 600; }}

QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {SUBTLE}; background: #FAFAFB; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; padding: 4px; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

QRadioButton, QCheckBox {{ spacing: 8px; background: transparent; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
                            background: white; }}
QRadioButton::indicator:checked {{ border: 5px solid {ACCENT}; width: 6px; height: 6px; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QLabel#badge {{ background: {ORANGE_SOFT}; color: {ORANGE}; border-radius: 9px; padding: 1px 7px;
               font-size: 8.5pt; font-weight: 700; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; border-radius: 4px;
                        background: white; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{check}"); }}

QTableView, QTreeView, QTreeWidget, QListWidget {{
    background: {SURFACE}; border: none; gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; alternate-background-color: #FCFCFD; }}
QTableView::item {{ border-bottom: 1px solid #F2F4F7; padding: 0 4px; }}
QTreeView::item {{ border-bottom: 1px solid #F2F4F7; padding: 6px 4px; }}
QTableView::item:selected, QTreeView::item:selected, QListWidget::item:selected {{
    background: {ACCENT_SOFT}; color: {TEXT}; }}
QTreeView::item:hover, QTableView::item:hover {{ background: #F9FAFB; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QHeaderView {{ background: {SURFACE}; border: none; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; font-weight: 600; font-size: 9pt;
    border: none; border-bottom: 1px solid {BORDER}; padding: 8px 6px; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D0D5DD; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D0D5DD; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 8px 10px;
            background: {SURFACE}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item:selected {{ background: {HOVER}; border-radius: 6px; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}
QSplitter::handle {{ background: {BG}; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QMessageBox {{ background: {SURFACE}; }}
"""


def apply_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: SURFACE, QPalette.AlternateBase: "#FCFCFD",
        QPalette.Text: TEXT, QPalette.Button: SURFACE, QPalette.ButtonText: TEXT, QPalette.ToolTipBase: TEXT,
        QPalette.ToolTipText: "#FFFFFF", QPalette.Highlight: ACCENT_SOFT, QPalette.HighlightedText: TEXT,
        QPalette.PlaceholderText: SUBTLE, QPalette.Link: ACCENT, QPalette.BrightText: "#FFFFFF",
        QPalette.Light: "#FFFFFF", QPalette.Midlight: BORDER, QPalette.Mid: BORDER_STRONG, QPalette.Dark: MUTED,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(SUBTLE))
    app.setPalette(pal)
    font = QFont("Segoe UI", 10) if os.name == "nt" else app.font()
    if os.name != "nt":
        font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())
