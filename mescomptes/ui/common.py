"""Widgets et utilitaires partagés par l'interface."""

import io
import os

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,  # noqa: E402
                               QLabel, QMessageBox, QTableView, QTreeWidgetItem, QWidget)

from .. import analytics as an  # noqa: E402
from ..db import KINDS, STATUS_LABELS  # noqa: E402
from ..money import fmt_eur  # noqa: E402

RED = QColor("#C0392B")
GREEN = QColor("#1E8449")
BLUE = QColor("#2471A3")
ORANGE = QColor("#CA6F1E")
GREY = QColor("#7F8C8D")
SECTION_BG = QColor("#DDEBF7")
TOTAL_BG = QColor("#EAF2E3")
STATUS_COLORS = {"none": ORANGE, "auto": BLUE, "manual": GREEN}

CHART_COLORS = ["#2E86C1", "#E67E22", "#27AE60", "#8E44AD", "#C0392B", "#16A085", "#F1C40F", "#7F8C8D",
                "#D35400", "#1ABC9C", "#9B59B6", "#34495E", "#E74C3C", "#3498DB", "#95A5A6"]

SORT_ROLE = Qt.UserRole + 1


def bold_font():
    f = QFont()
    f.setBold(True)
    return f


def error(parent, message, title="Erreur"):
    QMessageBox.warning(parent, title, str(message))


def info(parent, message, title="Mes Comptes"):
    QMessageBox.information(parent, title, str(message))


def confirm(parent, message, title="Confirmation"):
    return QMessageBox.question(parent, title, message, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


_last_dirs = {}


def save_path(parent, title, default_name, filter_):
    start = os.path.join(_last_dirs.get("save", os.path.expanduser("~")), default_name)
    path, _ = QFileDialog.getSaveFileName(parent, title, start, filter_)
    if path:
        _last_dirs["save"] = os.path.dirname(path)
    return path


def safe_filename(text):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in text).strip()


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


# ---------------------------------------------------------- sélecteurs
class CategoryCombo(QComboBox):
    """Liste déroulante des catégories (sous-catégories indentées)."""
    ALL = "__all__"
    NONE = "__none__"

    def __init__(self, parent=None, with_all=False, with_none=False, tops_only=False):
        super().__init__(parent)
        self.with_all, self.with_none, self.tops_only = with_all, with_none, tops_only
        self.setMaxVisibleItems(25)
        self.setMinimumContentsLength(22)

    def populate(self, db, keep=True):
        current = self.currentData() if keep else None
        self.blockSignals(True)
        self.clear()
        if self.with_all:
            self.addItem("Toutes les catégories", self.ALL)
        if self.with_none:
            self.addItem("⚠ À classer", self.NONE)
        for top, subs in db.category_tree():
            self.addItem(f"{top.name}   ({KINDS[top.kind].lower()})", top.id)
            idx = self.count() - 1
            self.setItemData(idx, bold_font(), Qt.FontRole)
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
            # hors bornes : on prend la borne la plus proche
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

    def __init__(self, parent=None, default="12 derniers mois", label="Période :"):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if label:
            lay.addWidget(QLabel(label))
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS)
        self.preset.setCurrentText(default)
        self.start = MonthCombo()
        self.end = MonthCombo()
        lay.addWidget(self.preset)
        lay.addWidget(QLabel("du"))
        lay.addWidget(self.start)
        lay.addWidget(QLabel("au"))
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
        lo = min(self.min_month, an.add_months(self.max_month, -23))
        hi = an.add_months(self.max_month, 12)  # permet de préparer un budget
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

    def set_period(self, start, end):
        self._busy = True
        self.preset.blockSignals(True)
        self.preset.setCurrentText("Personnalisée")
        self.preset.blockSignals(False)
        self.start.set_month(start)
        self.end.set_month(end)
        self._busy = False
        self.changed.emit(*self.period())

    def period(self):
        return self.start.month(), self.end.month()

    def label(self):
        return an.period_label(*self.period())


# --------------------------------------------------------------- graphiques
class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, height=4):
        self.figure = Figure(figsize=(8, height), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setMinimumHeight(220)

    def png_bytes(self, dpi=150):
        buf = io.BytesIO()
        self.figure.savefig(buf, format="png", dpi=dpi, facecolor="white")
        return buf.getvalue()


def euro_axis(ax):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f} €".replace(",", " ")))
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)


# ------------------------------------------------------ table d'opérations
class OperationsModel(QAbstractTableModel):
    HEADERS = ["Date", "Libellé", "Fournisseur", "Montant", "Catégorie", "Statut", "Note"]
    COL_DATE, COL_LABEL, COL_VENDOR, COL_AMOUNT, COL_CAT, COL_STATUS, COL_NOTE = range(7)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = [dict(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
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
            if c == self.COL_VENDOR:
                return r["vendor"]
            if c == self.COL_AMOUNT:
                return fmt_eur(r["amount"])
            if c == self.COL_CAT:
                return self.db.category_label(r["category_id"]) or "—"
            if c == self.COL_STATUS:
                return STATUS_LABELS.get(r["status"], r["status"])
            if c == self.COL_NOTE:
                return r["note"]
        elif role == SORT_ROLE:
            if c == self.COL_DATE:
                return f"{r['date']}{r['id']:010d}"
            if c == self.COL_AMOUNT:
                return r["amount"]
            return (self.data(index, Qt.DisplayRole) or "").casefold()
        elif role == Qt.ForegroundRole:
            if c == self.COL_AMOUNT:
                return QBrush(RED if r["amount"] < 0 else GREEN)
            if c == self.COL_STATUS:
                return QBrush(STATUS_COLORS.get(r["status"], GREY))
            if c == self.COL_CAT and r["category_id"] is None:
                return QBrush(ORANGE)
        elif role == Qt.TextAlignmentRole and c == self.COL_AMOUNT:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.FontRole and c == self.COL_STATUS and r["status"] == "none":
            return bold_font()
        elif role == Qt.ToolTipRole and c == self.COL_LABEL:
            return r["label"]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.column() == self.COL_NOTE and role == Qt.EditRole:
            r = self.rows[index.row()]
            r["note"] = str(value)
            self.db.set_note(r["id"], r["note"])
            self.dataChanged.emit(index, index)
            return True
        return False

    def total(self):
        return sum(r["amount"] for r in self.rows)


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
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(OperationsModel.COL_LABEL, QHeaderView.Stretch)
        for col, w in ((0, 85), (2, 170), (3, 100), (4, 210), (5, 120), (6, 140)):
            self.setColumnWidth(col, w)

    def set_rows(self, rows):
        self.model_.set_rows(rows)

    def selected_rows(self):
        idx = self.selectionModel().selectedRows()
        return [self.model_.rows[self.proxy.mapToSource(i).row()] for i in idx]

    def row_at(self, proxy_index):
        return self.model_.rows[self.proxy.mapToSource(proxy_index).row()]

    def visible_rows(self):
        return [self.model_.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()]
                for i in range(self.proxy.rowCount())]
