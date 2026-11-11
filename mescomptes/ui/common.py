"""Widgets et utilitaires partagés par l'interface."""

import io
import os

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, QSize, QSortFilterProxyModel, Qt,  # noqa: E402
                            Signal)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout,  # noqa: E402
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QStyle,
                               QStyledItemDelegate, QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import analytics as an  # noqa: E402
from ..db import KINDS, STATUS_LABELS  # noqa: E402
from ..money import fmt_eur  # noqa: E402
from . import theme as T  # noqa: E402

RED = QColor(T.RED)
GREEN = QColor(T.GREEN)
BLUE = QColor(T.BLUE)
ORANGE = QColor(T.ORANGE)
GREY = QColor(T.MUTED)
TEXT = QColor(T.TEXT)
SECTION_BG = QColor(T.SECTION)
TOTAL_BG = QColor(T.TOTAL)
STATUS_COLORS = {"none": ORANGE, "auto": BLUE, "manual": GREEN}
STATUS_SHORT = {"none": "À classer", "auto": "À vérifier", "manual": "Validée"}
CHART_COLORS = T.CHART_COLORS

SORT_ROLE = Qt.UserRole + 1
COLOR_ROLE = Qt.UserRole + 2


def bold_font(size=None):
    f = QFont()
    f.setBold(True)
    if size:
        f.setPointSizeF(size)
    return f


# ------------------------------------------------------------- messages
def error(parent, message, title="Erreur"):
    QMessageBox.warning(parent, title, str(message))


def info(parent, message, title="Mes Comptes"):
    QMessageBox.information(parent, title, str(message))


def confirm(parent, message, title="Confirmation"):
    box = QMessageBox(QMessageBox.Question, title, message, QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("Oui")
    box.button(QMessageBox.No).setText("Non")
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


_last_dirs = {}


def save_path(parent, title, default_name, filter_):
    start = os.path.join(_last_dirs.get("save", os.path.expanduser("~")), default_name)
    path, _ = QFileDialog.getSaveFileName(parent, title, start, filter_)
    if path:
        _last_dirs["save"] = os.path.dirname(path)
    return path


def safe_filename(text):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in text).strip()


# ------------------------------------------------------------- mise en page
def button(text, icon_name=None, kind=None, tooltip=None, slot=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon_name:
        color = "#FFFFFF" if kind == "primary" else (T.ACCENT if kind == "link" else T.MUTED)
        b.setIcon(T.icon(icon_name, color))
        b.setIconSize(QSize(16, 16))
    if tooltip:
        b.setToolTip(tooltip)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text="", name=None, wrap=False):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class Card(QFrame):
    """Panneau blanc à bords arrondis."""

    def __init__(self, parent=None, margins=(16, 14, 16, 14), spacing=10):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(*margins)
        self.layout_.setSpacing(spacing)

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.layout_.addWidget(w, stretch)
        else:
            self.layout_.addLayout(w, stretch)
        return w


class Page(QWidget):
    """Page de l'application : en-tête (titre, sous-titre, actions) puis contenu."""

    def __init__(self, title, subtitle="", parent=None, scroll=False):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 20)
        self.root.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label(title, "title")
        titles.addWidget(self.title_label)
        self.subtitle_label = label(subtitle, "subtitle", wrap=True)
        if subtitle:
            titles.addWidget(self.subtitle_label)
        head.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        self.root.addLayout(head)
        self.body = self.root
        if scroll:
            from PySide6.QtWidgets import QScrollArea
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            inner = QWidget()
            inner.setObjectName("page")
            inner.setAttribute(Qt.WA_StyledBackground, True)
            self.body = QVBoxLayout(inner)
            self.body.setContentsMargins(0, 0, 6, 0)
            self.body.setSpacing(14)
            area.setWidget(inner)
            self.root.addWidget(area, 1)

    def add_action(self, w):
        self.actions.addWidget(w)
        return w

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.body.addWidget(w, stretch)
        else:
            self.body.addLayout(w, stretch)
        return w

    def refresh(self):
        pass


def hline():
    f = QFrame()
    f.setObjectName("hline")
    return f


def search_box(placeholder):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    e.addAction(T.icon("search", T.SUBTLE), QLineEdit.LeadingPosition)
    return e


def style_tree(tree):
    tree.setAlternatingRowColors(False)
    tree.setUniformRowHeights(True)
    tree.setIndentation(18)
    tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    tree.setFrameShape(QFrame.NoFrame)


# ----------------------------------------------------------------- arbres
class SortItem(QTreeWidgetItem):
    """Élément d'arbre triable sur une valeur numérique stockée dans SORT_ROLE."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(col, SORT_ROLE), other.data(col, SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return self.text(col).casefold() < other.text(col).casefold()


def set_money(item, col, cents, colorize=False, invert=False, blank_zero=True, signed=False):
    """Écrit un montant dans une cellule d'arbre."""
    item.setText(col, fmt_eur(cents, blank_zero=blank_zero, signed=signed))
    item.setData(col, SORT_ROLE, cents or 0)
    item.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
    if colorize and cents:
        good = (cents > 0) != invert
        item.setForeground(col, QBrush(GREEN if good else RED))


def style_row(item, ncols, bold=False, bg=None, fg=None):
    for c in range(ncols):
        if bold:
            item.setFont(c, bold_font())
        if bg is not None:
            item.setBackground(c, QBrush(bg))
        if fg is not None:
            item.setForeground(c, QBrush(fg))


class DotDelegate(QStyledItemDelegate):
    """Colonne 0 d'un arbre : pastille de couleur (COLOR_ROLE) avant le texte."""

    def paint(self, painter, option, index):
        color = index.data(COLOR_ROLE)
        if color is None:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        text = option.text
        option.text = ""
        style = option.widget.style() if option.widget else None
        style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        d = 9
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(r.left() + 4, r.center().y() - d / 2 + 1, d, d))
        fg = index.data(Qt.ForegroundRole)
        if fg is None:
            pen = QColor(T.TEXT)
        else:
            pen = fg.color() if hasattr(fg, "color") else QColor(fg)
        painter.setPen(pen)
        painter.setFont(option.font)
        painter.drawText(r.adjusted(4 + d + 8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


# ---------------------------------------------------------- sélecteurs
class CategoryCombo(QComboBox):
    """Liste déroulante des catégories (sous-catégories indentées)."""
    ALL = "__all__"
    NONE = "__none__"

    def __init__(self, parent=None, with_all=False, with_none=False, tops_only=False):
        super().__init__(parent)
        self.with_all, self.with_none, self.tops_only = with_all, with_none, tops_only
        self.setMaxVisibleItems(25)
        self.setMinimumContentsLength(20)

    def populate(self, db, keep=True):
        current = self.currentData() if keep else None
        self.blockSignals(True)
        self.clear()
        if self.with_all:
            self.addItem("Toutes les catégories", self.ALL)
        if self.with_none:
            self.addItem(T.icon("alert", T.ORANGE), "À classer", self.NONE)
        for top, subs in db.category_tree():
            self.addItem(_dot_icon(T.category_color(db, top.id)), top.name, top.id)
            self.setItemData(self.count() - 1, bold_font(), Qt.FontRole)
            if not self.tops_only:
                for s in subs:
                    self.addItem(f"      {s.name}", s.id)
        i = self.findData(current) if current is not None else -1
        self.setCurrentIndex(i if i >= 0 else 0)
        self.blockSignals(False)

    def set_value(self, value):
        i = self.findData(value)
        if i >= 0:
            self.setCurrentIndex(i)


def _dot_icon(color, size=10):
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, size * 2 - 4, size * 2 - 4)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class CategoryPicker(QWidget):
    """Choix d'une catégorie avec recherche (liste arborescente)."""
    chosen = Signal(object)          # double-clic / Entrée
    selection_changed = Signal(object)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.search = search_box("Rechercher une catégorie…")
        lay.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("picker")
        self.tree.setItemDelegateForColumn(0, DotDelegate(self.tree))
        self.tree.setIndentation(14)
        self.tree.setStyleSheet(f"QTreeWidget#picker {{ border: 1px solid {T.BORDER}; border-radius: 8px; }}")
        lay.addWidget(self.tree, 1)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._enter)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.chosen.emit(it.data(0, Qt.UserRole)))
        self.tree.currentItemChanged.connect(
            lambda it, _p: self.selection_changed.emit(it.data(0, Qt.UserRole) if it else None))
        self.populate()

    def populate(self):
        current = self.value()
        self.tree.clear()
        for top, subs in self.db.category_tree():
            it = QTreeWidgetItem(self.tree, [top.name])
            it.setData(0, Qt.UserRole, top.id)
            it.setData(0, COLOR_ROLE, T.category_color(self.db, top.id))
            it.setFont(0, bold_font())
            for s in subs:
                c = QTreeWidgetItem(it, [s.name])
                c.setData(0, Qt.UserRole, s.id)
            it.setExpanded(True)
        if current is not None:
            self.set_value(current)

    def _filter(self, text):
        q = text.strip().casefold()
        first = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_match = q in top.text(0).casefold()
            any_child = False
            for j in range(top.childCount()):
                ch = top.child(j)
                m = not q or top_match or q in ch.text(0).casefold()
                ch.setHidden(not m)
                if m and q and first is None and not top_match:
                    first = ch
                any_child |= m
            top.setHidden(bool(q) and not (top_match or any_child))
            if q and top_match and first is None:
                first = top
        if first is not None:
            self.tree.setCurrentItem(first)

    def _enter(self):
        it = self.tree.currentItem()
        if it and not it.isHidden():
            self.chosen.emit(it.data(0, Qt.UserRole))

    def value(self):
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        return it.data(0, Qt.UserRole) if it else None

    def set_value(self, cat_id):
        self.tree.setCurrentItem(None)
        if cat_id is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, Qt.UserRole) == cat_id:
                self.tree.setCurrentItem(top)
                return
            for j in range(top.childCount()):
                if top.child(j).data(0, Qt.UserRole) == cat_id:
                    self.tree.setCurrentItem(top.child(j))
                    self.tree.scrollToItem(top.child(j))
                    return


class MonthCombo(QComboBox):
    def set_months(self, months, keep=True):
        current = self.currentData()
        self.blockSignals(True)
        self.clear()
        for m in months:
            self.addItem(an.month_label(m, full=True).capitalize(), m)
        if keep and current:
            self.set_month(current)
        self.blockSignals(False)

    def set_month(self, m):
        i = self.findData(m)
        if i < 0 and self.count():
            i = 0 if m < self.itemData(0) else self.count() - 1
        if i >= 0:
            self.setCurrentIndex(i)

    def month(self):
        return self.currentData()


class PeriodSelector(QWidget):
    """Choix d'une période en mois, avec préréglages relatifs au dernier mois du relevé."""
    changed = Signal(str, str)

    PRESETS = ["Dernier mois", "3 derniers mois", "6 derniers mois", "12 derniers mois", "Année en cours",
               "Année précédente", "Tout l'historique", "Personnalisée"]

    def __init__(self, parent=None, default="12 derniers mois", label=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if label:
            lbl = QLabel(label)
            lbl.setObjectName("muted")
            lay.addWidget(lbl)
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS)
        self.preset.setCurrentText(default)
        self.start = MonthCombo()
        self.end = MonthCombo()
        lay.addWidget(self.preset)
        arrow = QLabel("→")
        arrow.setObjectName("muted")
        lay.addWidget(self.start)
        lay.addWidget(arrow)
        lay.addWidget(self.end)
        self.min_month = self.max_month = an.current_month()
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.start.currentIndexChanged.connect(self._custom)
        self.end.currentIndexChanged.connect(self._custom)
        self._busy = False
        self.set_bounds(None, None)

    def set_bounds(self, min_date, max_date):
        """Bornes issues des données (dates 'AAAA-MM-JJ' ou None)."""
        self.max_month = an.ym(max_date) if max_date else an.current_month()
        self.min_month = an.ym(min_date) if min_date else an.add_months(self.max_month, -11)
        # marge large : comparaisons N-1 et préparation de budget
        lo = an.add_months(min(self.min_month, an.add_months(self.max_month, -23)), -12)
        hi = an.add_months(self.max_month, 12)
        months = an.month_range(lo, hi)
        self._busy = True
        self.start.set_months(months)
        self.end.set_months(months)
        self._busy = False
        if self.preset.currentText() != "Personnalisée":
            self._apply_preset(self.preset.currentText(), emit=False)

    def _apply_preset(self, name, emit=True):
        last = self.max_month
        year = last[:4]
        ranges = {
            "Dernier mois": (last, last),
            "3 derniers mois": (an.add_months(last, -2), last),
            "6 derniers mois": (an.add_months(last, -5), last),
            "12 derniers mois": (an.add_months(last, -11), last),
            "Année en cours": (f"{year}-01", last),
            "Année précédente": (f"{int(year) - 1}-01", f"{int(year) - 1}-12"),
            "Tout l'historique": (self.min_month, last),
        }
        if name not in ranges:
            return
        s, e = ranges[name]
        self._busy = True
        self.start.set_month(s)
        self.end.set_month(e)
        self._busy = False
        if emit:
            self.changed.emit(*self.period())

    def _custom(self):
        if self._busy:
            return
        self.preset.blockSignals(True)
        self.preset.setCurrentText("Personnalisée")
        self.preset.blockSignals(False)
        if self.start.month() and self.end.month() and self.start.month() > self.end.month():
            self._busy = True
            self.end.set_month(self.start.month())
            self._busy = False
        self.changed.emit(*self.period())

    def set_period(self, start, end, emit=True):
        self._busy = True
        self.preset.blockSignals(True)
        self.preset.setCurrentText("Personnalisée")
        self.preset.blockSignals(False)
        self.start.set_month(start)
        self.end.set_month(end)
        self._busy = False
        if emit:
            self.changed.emit(*self.period())

    def period(self):
        return self.start.month(), self.end.month()

    def label(self):
        return an.period_label(*self.period())


# --------------------------------------------------------------- graphiques
class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, height=4):
        self.figure = Figure(figsize=(8, height), dpi=100, layout="constrained", facecolor="white")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setMinimumHeight(200)

    def png_bytes(self, dpi=150):
        buf = io.BytesIO()
        self.figure.savefig(buf, format="png", dpi=dpi, facecolor="white")
        return buf.getvalue()


matplotlib.rcParams.update({
    "font.family": ["Segoe UI"] if os.name == "nt" else ["DejaVu Sans"],
    "font.size": 9, "axes.edgecolor": T.BORDER_STRONG, "axes.labelcolor": T.MUTED, "xtick.color": T.MUTED,
    "ytick.color": T.MUTED, "axes.titlecolor": T.TEXT, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.titlesize": 10, "legend.frameon": False,
})


def euro_axis(ax):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f} €".replace(",", " ")))
    ax.grid(axis="y", color=T.BORDER, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="both", length=0)


# ------------------------------------------------------ table d'opérations
class OperationsModel(QAbstractTableModel):
    HEADERS = ["Date", "Libellé", "Catégorie", "Montant", "Statut", "Note"]
    COL_DATE, COL_LABEL, COL_CAT, COL_AMOUNT, COL_STATUS, COL_NOTE = range(6)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = [dict(r) for r in rows]
        self.endResetModel()

    def update_rows(self, rows_by_id):
        for i, r in enumerate(self.rows):
            if r["id"] in rows_by_id:
                self.rows[i] = dict(rows_by_id[r["id"]])
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(self.HEADERS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.HEADERS[section].upper()
            if role == Qt.TextAlignmentRole and section == self.COL_AMOUNT:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == self.COL_NOTE:
            f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == self.COL_DATE:
                d = r["date"]
                return f"{d[8:10]}/{d[5:7]}/{d[:4]}"
            if c == self.COL_LABEL:
                return r["label"]
            if c == self.COL_AMOUNT:
                return fmt_eur(r["amount"], signed=True)
            if c == self.COL_CAT:
                return self.db.category_label(r["category_id"]) or "À classer"
            if c == self.COL_STATUS:
                return STATUS_SHORT.get(r["status"], r["status"])
            if c == self.COL_NOTE:
                return r["note"]
        elif role == SORT_ROLE:
            if c == self.COL_DATE:
                return f"{r['date']}{r['id']:010d}"
            if c == self.COL_AMOUNT:
                return r["amount"]
            return (self.data(index, Qt.DisplayRole) or "").casefold()
        elif role == COLOR_ROLE:
            if c == self.COL_CAT:
                return T.category_color(self.db, r["category_id"]) if r["category_id"] else QColor(T.ORANGE)
            if c == self.COL_STATUS:
                return STATUS_COLORS.get(r["status"], GREY)
        elif role == Qt.ForegroundRole:
            if c == self.COL_AMOUNT:
                return QBrush(GREEN if r["amount"] > 0 else TEXT)
            if c == self.COL_DATE:
                return QBrush(GREY)
        elif role == Qt.FontRole and c == self.COL_AMOUNT:
            return bold_font()
        elif role == Qt.TextAlignmentRole and c == self.COL_AMOUNT:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole:
            if c == self.COL_LABEL:
                return r["label"] + (f"\nFournisseur : {r['vendor']}" if r["vendor"] else "")
            if c == self.COL_STATUS:
                return STATUS_LABELS.get(r["status"])
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.column() == self.COL_NOTE and role == Qt.EditRole:
            r = self.rows[index.row()]
            r["note"] = str(value)
            self.db.set_note(r["id"], r["note"])
            self.dataChanged.emit(index, index)
            return True
        return False


class PillDelegate(QStyledItemDelegate):
    """Étiquette arrondie colorée (catégorie) ou pastille + texte (statut)."""

    def __init__(self, parent=None, dot_only=False):
        super().__init__(parent)
        self.dot_only = dot_only

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        text = option.text
        option.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        color = QColor(index.data(COLOR_ROLE) or T.MUTED)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 0, -4, 0)
        fm = option.fontMetrics
        if self.dot_only:
            d = 8
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(r.left(), r.center().y() - d / 2 + 1, d, d))
            painter.setPen(QPen(color.darker(115)))
            painter.drawText(r.adjusted(d + 8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        else:
            text = fm.elidedText(text, Qt.ElideRight, r.width() - 26)
            w = fm.horizontalAdvance(text) + 26
            h = fm.height() + 8
            pill = QRectF(r.left(), r.center().y() - h / 2 + 1, w, h)
            painter.setBrush(T.soft(color, 30))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(pill, h / 2, h / 2)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(pill.left() + 9, pill.center().y() - 3.5, 7, 7))
            painter.setPen(QPen(color.darker(140)))
            painter.drawText(pill.adjusted(20, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class OperationsView(QTableView):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.model_ = OperationsModel(db, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model_)
        self.proxy.setSortRole(SORT_ROLE)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.sortByColumn(OperationsModel.COL_DATE, Qt.DescendingOrder)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.setItemDelegateForColumn(OperationsModel.COL_CAT, PillDelegate(self))
        self.setItemDelegateForColumn(OperationsModel.COL_STATUS, PillDelegate(self, dot_only=True))
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(OperationsModel.COL_LABEL, QHeaderView.Stretch)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, w in ((0, 96), (2, 230), (3, 110), (4, 110), (5, 120)):
            self.setColumnWidth(col, w)

    def set_rows(self, rows):
        self.model_.set_rows(rows)

    def selected_rows(self):
        idx = self.selectionModel().selectedRows()
        return [self.model_.rows[self.proxy.mapToSource(i).row()] for i in idx]

    def visible_rows(self):
        return [self.model_.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()]
                for i in range(self.proxy.rowCount())]

    def select_id(self, op_id):
        for i in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(i, 0))
            if self.model_.rows[src.row()]["id"] == op_id:
                self.selectRow(i)
                self.scrollTo(self.proxy.index(i, 0))
                return True
        return False

    def proxy_row_of(self, op_id):
        for i in range(self.proxy.rowCount()):
            if self.model_.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()]["id"] == op_id:
                return i
        return -1


__all__ = ["KINDS"]
