"""Pages d'analyse : Synthèse (catégories × mois), Comparaison, Budget."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QSpinBox,
                               QTreeWidget, QVBoxLayout)

from .. import analytics as an
from ..exporters import MONEY, PCT, RATIO, TEXT, TableData, export_excel, export_pdf, report_to_rows
from ..money import fmt_eur, fmt_pct, parse_eur_input, pct_change
from . import theme as T
from .common import (COLOR_ROLE, GREEN, GREY, ORANGE, RED, SECTION_BG, SORT_ROLE, TEXT as TEXT_COLOR, TOTAL_BG,
                     Card, DotDelegate, Page, PeriodSelector, SortItem, bold_font, button, confirm, error, info,
                     label, safe_filename, save_path, set_money, style_row, style_tree)
from .operations_tab import OperationsPanel

NODE_ROLE = Qt.UserRole + 10


class OperationsDialog(QDialog):
    """Liste des opérations derrière un chiffre, avec classement possible."""

    def __init__(self, db, title, cat_ids, start_month, end_month, parent=None):
        super().__init__(parent)
        self.db, self.cat_ids, self.start, self.end = db, cat_ids, start_month, end_month
        self.setWindowTitle(title)
        self.resize(1100, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label(title, "title"))
        lay.addWidget(label(an.period_label(start_month, end_month), "subtitle"))
        card = Card()
        self.panel = OperationsPanel(db, card)
        self.panel.changed.connect(self.reload)
        card.add(self.panel, 1)
        lay.addWidget(card, 1)
        self.dirty = False
        self.reload(first=True)

    def reload(self, first=False):
        if not first:
            self.dirty = True
        kw = {"uncategorized": True} if self.cat_ids == [None] else {"cat_ids": self.cat_ids}
        self.panel.set_rows(self.db.operations(start=an.month_first_day(self.start),
                                               end=an.month_last_day(self.end), **kw))


class ReportTree(QTreeWidget):
    """Arbre catégories avec sections et totaux."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        style_tree(self)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.header().setStretchLastSection(False)
        self.setItemDelegateForColumn(0, DotDelegate(self))

    def fill(self, report, headers, value_writer, expanded=False):
        self.clear()
        self.setColumnCount(len(headers))
        self.setHeaderLabels([h.upper() for h in headers])
        for c in range(1, len(headers)):
            self.headerItem().setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
        n = len(headers)
        for title, kind, nodes in report.sections:
            sec = SortItem(self, [title.upper()])
            style_row(sec, n, bold=True, bg=SECTION_BG, fg=GREY)
            for node in nodes:
                it = SortItem(sec, [node.label])
                it.setData(0, NODE_ROLE, node)
                it.setData(0, COLOR_ROLE, T.category_color(self.db, node.cat_id) if node.cat_id
                           else QColor_(T.ORANGE))
                value_writer(it, node)
                for c in range(n):
                    it.setFont(c, bold_font())
                for ch in node.children:
                    c_it = SortItem(it, [ch.label])
                    c_it.setData(0, NODE_ROLE, ch)
                    value_writer(c_it, ch)
                it.setExpanded(expanded)
            sec.setExpanded(True)
        for t in report.totals:
            it = SortItem(self, [t.label])
            value_writer(it, t)
            style_row(it, n, bold=True, bg=TOTAL_BG)
        self.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.setColumnWidth(0, 300)
        for c in range(1, n):
            self.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)


def QColor_(c):
    from PySide6.QtGui import QColor
    return QColor(c)


def export_buttons(page, excel_cb, pdf_cb):
    page.add_action(button("Excel", "download", slot=excel_cb, tooltip="Exporter en Excel"))
    page.add_action(button("PDF", "file", slot=pdf_cb, tooltip="Exporter en PDF"))


def do_export(parent, kind, table, default_name, images=()):
    ext = "xlsx" if kind == "excel" else "pdf"
    path = save_path(parent, "Exporter", f"{safe_filename(default_name)}.{ext}",
                     "Excel (*.xlsx)" if ext == "xlsx" else "PDF (*.pdf)")
    if not path:
        return
    try:
        if ext == "xlsx":
            export_excel(path, [table])
        else:
            export_pdf(path, [table], images=images, title=table.title)
    except Exception as e:  # noqa: BLE001
        error(parent, f"Export impossible : {e}")
        return
    info(parent, f"Export enregistré :\n{path}")


# ==================================================================== Synthèse
class SummaryTab(Page):
    changed = Signal()

    MODES = ["Montants", "Écart vs mois précédent (€)", "Écart vs mois précédent (%)"]

    def __init__(self, db, parent=None):
        super().__init__("Synthèse mensuelle", "Vos revenus et dépenses par catégorie, mois par mois. "
                                               "Double-cliquez sur un montant pour voir les opérations.", parent)
        self.db = db
        export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf"))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addSpacing(10)
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        bar.addWidget(self.mode)
        bar.addStretch()
        self.expand = button("Tout déplier", None, "ghost")
        self.expand.setCheckable(True)
        bar.addWidget(self.expand)
        self.add(bar)
        card = Card(margins=(0, 4, 0, 4))
        self.tree = ReportTree(db, card)
        self.tree.itemDoubleClicked.connect(self._open)
        card.add(self.tree, 1)
        self.add(card, 1)
        self.period.changed.connect(self.reload)
        self.mode.currentIndexChanged.connect(self.reload)
        self.expand.toggled.connect(self._toggle_expand)

    def refresh(self):
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def _toggle_expand(self, on):
        self.expand.setText("Tout replier" if on else "Tout déplier")
        if on:
            self.tree.expandAll()
        else:
            self.tree.collapseAll()
            for i in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(i).setExpanded(True)

    def reload(self, *_):
        start, end = self.period.period()
        report = an.pivot(self.db, an.add_months(start, -1), end)  # un mois de plus pour l'écart du 1er mois
        months = an.month_range(start, end)
        self.report, self.months = report, months
        mode = self.mode.currentIndex()
        headers = ["Catégorie"] + [an.month_label(m) for m in months] + (
            ["Total", "Moyenne / mois"] if mode == 0 else [])

        def writer(item, node):
            invert = node.kind == "depense" or node.label == "Total dépenses"
            for i, m in enumerate(months, start=1):
                v = node.values.get(m, 0)
                before = node.values.get(an.add_months(m, -1), 0)
                if mode == 0:
                    set_money(item, i, v)
                elif mode == 1:
                    set_money(item, i, v - before, colorize=True, invert=invert, signed=True)
                else:
                    p = pct_change(v, before)
                    item.setText(i, fmt_pct(p))
                    item.setData(i, SORT_ROLE, p if p is not None else 0)
                    item.setTextAlignment(i, Qt.AlignRight | Qt.AlignVCenter)
                    if p:
                        item.setForeground(i, RED if (p > 0) == invert else GREEN)
            if mode == 0:
                total = node.total(months)
                set_money(item, len(months) + 1, total)
                set_money(item, len(months) + 2, round(total / max(len(months), 1)))
                item.setForeground(len(months) + 2, GREY)

        self.tree.fill(report, headers, writer, expanded=self.expand.isChecked())

    def _open(self, item, col):
        node = item.data(0, NODE_ROLE)
        if node is None:
            return
        if 1 <= col <= len(self.months):
            start = end = self.months[col - 1]
        else:
            start, end = self.months[0], self.months[-1]
        dlg = OperationsDialog(self.db, node.label, node.cat_ids, start, end, self)
        dlg.exec()
        if dlg.dirty:
            self.changed.emit()

    def table(self):
        mode = self.mode.currentIndex()
        months = self.months
        headers = ["Catégorie"] + [an.month_label(m) for m in months]
        if mode == 0:
            headers += ["Total", "Moyenne / mois"]
        types = [TEXT] + [PCT if mode == 2 else MONEY] * (len(headers) - 1)
        t = TableData("Synthèse par catégorie", f"{self.period.label()} — {self.MODES[mode]}", headers, types)

        def values(node):
            out = []
            for m in months:
                v, before = node.values.get(m, 0), node.values.get(an.add_months(m, -1), 0)
                out.append(v if mode == 0 else (v - before if mode == 1 else pct_change(v, before)))
            if mode == 0:
                total = node.total(months)
                out += [total, round(total / max(len(months), 1))]
            return out

        report_to_rows(t, self.report, values)
        return t

    def export(self, kind):
        do_export(self, kind, self.table(), f"synthese {self.period.label()}")


# ================================================================= Comparaison
class CompareTab(Page):
    changed = Signal()

    MODES = ["Mois précédent", "Même mois l'année précédente", "Même période l'année précédente (N / N-1)",
             "Période libre"]
    FREE = 3

    def __init__(self, db, parent=None):
        super().__init__("Comparaison", "Comparez deux périodes, catégorie par catégorie. "
                                        "Vous pouvez modifier librement la période de référence.", parent)
        self.db = db
        export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf"))
        card = Card(margins=(16, 12, 16, 12), spacing=8)
        r1 = QHBoxLayout()
        r1.addWidget(self._tag("A"))
        self.pa = PeriodSelector(self, default="Dernier mois", label="Période analysée")
        r1.addWidget(self.pa)
        r1.addStretch()
        card.add(r1)
        r2 = QHBoxLayout()
        r2.addWidget(self._tag("B"))
        r2.addWidget(label("Comparer avec", "muted"))
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        r2.addWidget(self.mode)
        self.pb = PeriodSelector(self, default="Dernier mois", label=None)
        self.pb.preset.hide()
        r2.addWidget(self.pb)
        r2.addStretch()
        card.add(r2)
        self.add(card)
        tcard = Card(margins=(0, 4, 0, 4))
        self.tree = ReportTree(db, tcard)
        self.tree.itemDoubleClicked.connect(self._open)
        tcard.add(self.tree, 1)
        self.add(tcard, 1)
        self.report = None
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.pa.changed.connect(self._a_changed)
        self.pb.changed.connect(self._b_changed)

    @staticmethod
    def _tag(letter):
        lbl = label(letter)
        lbl.setFixedSize(24, 24)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"background:{T.ACCENT_SOFT}; color:{T.ACCENT}; border-radius:12px; font-weight:700")
        return lbl

    def refresh(self):
        bounds = self.db.date_bounds()
        self.pa.set_bounds(*bounds)
        self.pb.set_bounds(*bounds)
        self._sync_b()

    def _mode_changed(self, *_):
        m = self.mode.currentIndex()
        if m in (0, 1) and self.pa.preset.currentText() not in ("Dernier mois", "Personnalisée"):
            self.pa.preset.setCurrentText("Dernier mois")
        elif m == 2 and self.pa.preset.currentText() == "Dernier mois":
            self.pa.preset.setCurrentText("Année en cours")
        self._sync_b()

    def _a_changed(self, *_):
        self._sync_b()

    def _b_changed(self, *_):
        # modification manuelle de B : passage en période libre
        if self.mode.currentIndex() != self.FREE:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self.FREE)
            self.mode.blockSignals(False)
        self.reload()

    def _sync_b(self):
        m = self.mode.currentIndex()
        a0, a1 = self.pa.period()
        if a0 is None:
            return
        if m == 0:
            n = len(an.month_range(a0, a1))
            b = (an.add_months(a0, -n), an.add_months(a1, -n))
        elif m in (1, 2):
            b = (an.add_months(a0, -12), an.add_months(a1, -12))
        else:
            b = None
        if b:
            self.pb.blockSignals(True)
            self.pb.set_period(*b, emit=False)
            self.pb.blockSignals(False)
        self.reload()

    def reload(self, *_):
        a, b = self.pa.period(), self.pb.period()
        if None in a or None in b:
            return
        self.report = an.compare(self.db, a, b)
        la, lb = an.period_label(*a), an.period_label(*b)
        self.headers = ["Catégorie", f"A · {la}", f"B · {lb}", "Écart A − B", "Écart %"]

        def writer(item, node):
            va, vb = node.values.get("A", 0), node.values.get("B", 0)
            invert = node.kind == "depense" or node.label == "Total dépenses"
            set_money(item, 1, va)
            set_money(item, 2, vb)
            set_money(item, 3, va - vb, colorize=True, invert=invert, signed=True)
            p = pct_change(va, vb)
            item.setText(4, fmt_pct(p))
            item.setData(4, SORT_ROLE, p if p is not None else 0)
            item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
            if p:
                item.setForeground(4, RED if (p > 0) == invert else GREEN)

        self.tree.fill(self.report, self.headers, writer)

    def _open(self, item, col):
        node = item.data(0, NODE_ROLE)
        if node is None:
            return
        period = self.pb.period() if col == 2 else self.pa.period()
        dlg = OperationsDialog(self.db, node.label, node.cat_ids, *period, parent=self)
        dlg.exec()
        if dlg.dirty:
            self.changed.emit()

    def export(self, kind):
        t = TableData("Comparaison", f"A : {self.pa.label()} — B : {self.pb.label()}", self.headers,
                      [TEXT, MONEY, MONEY, MONEY, PCT])
        report_to_rows(t, self.report, lambda n: [n.values.get("A", 0), n.values.get("B", 0),
                                                  n.values.get("A", 0) - n.values.get("B", 0),
                                                  pct_change(n.values.get("A", 0), n.values.get("B", 0))])
        do_export(self, kind, t, "comparaison")


__all__ = ["TEXT_COLOR"]
