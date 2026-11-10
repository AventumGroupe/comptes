"""Onglets d'analyse : Synthèse (catégories × mois), Comparaison, Budget."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox,
                               QTreeWidget, QVBoxLayout, QWidget, QAbstractItemView)

from .. import analytics as an
from ..exporters import MONEY, PCT, RATIO, TEXT, TableData, export_excel, export_pdf, report_to_rows
from ..money import fmt_eur, fmt_pct, parse_eur_input, pct_change
from .common import (GREY, SECTION_BG, SORT_ROLE, TOTAL_BG, PeriodSelector, SortItem, error, info, safe_filename,
                     save_path, set_money, style_row)
from .operations_tab import OperationsPanel

NODE_ROLE = Qt.UserRole + 10


class OperationsDialog(QDialog):
    """Liste des opérations derrière un chiffre, avec classement possible."""

    def __init__(self, db, title, cat_ids, start_month, end_month, parent=None):
        super().__init__(parent)
        self.db, self.cat_ids, self.start, self.end = db, cat_ids, start_month, end_month
        self.setWindowTitle(title)
        self.resize(1100, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{title}</b> — {an.period_label(start_month, end_month)}"))
        self.panel = OperationsPanel(db, self)
        self.panel.changed.connect(self.reload)
        lay.addWidget(self.panel)
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
    open_operations = Signal(object, str, str)  # (node, mois début, mois fin)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.header().setDefaultAlignment(Qt.AlignCenter)
        self.header().setStretchLastSection(False)

    def fill(self, report, headers, value_writer, expanded=False):
        """value_writer(item, node) écrit les colonnes 1..n."""
        self.clear()
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        n = len(headers)
        for title, kind, nodes in report.sections:
            sec = SortItem(self, [title.upper()])
            style_row(sec, n, bold=True, bg=SECTION_BG)
            sec.setFirstColumnSpanned(False)
            for node in nodes:
                it = SortItem(sec, [node.label])
                it.setData(0, NODE_ROLE, node)
                value_writer(it, node)
                style_row(it, n, bold=True)
                for ch in node.children:
                    c = SortItem(it, [ch.label])
                    c.setData(0, NODE_ROLE, ch)
                    value_writer(c, ch)
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


def _export_buttons(parent, excel_cb, pdf_cb):
    b1 = QPushButton("Excel…")
    b1.clicked.connect(excel_cb)
    b2 = QPushButton("PDF…")
    b2.clicked.connect(pdf_cb)
    return [QLabel("Exporter :"), b1, b2]


def _do_export(parent, kind, table, default_name, images=()):
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
class SummaryTab(QWidget):
    changed = Signal()

    MODES = ["Montants", "Écart vs mois précédent (€)", "Écart vs mois précédent (%)"]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Afficher :"))
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        bar.addWidget(self.mode)
        self.expand = QPushButton("Tout déplier")
        self.expand.setCheckable(True)
        bar.addWidget(self.expand)
        bar.addStretch()
        for w in _export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf")):
            bar.addWidget(w)
        lay.addLayout(bar)
        hint = QLabel("Double-cliquez sur un montant pour voir (et corriger) les opérations correspondantes.")
        hint.setStyleSheet("color:#7F8C8D")
        lay.addWidget(hint)
        self.tree = ReportTree(self)
        self.tree.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.tree, 1)
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

    def _compute(self):
        start, end = self.period.period()
        prev = an.add_months(start, -1)
        report = an.pivot(self.db, prev, end)  # un mois de plus pour l'écart du premier mois
        months = an.month_range(start, end)
        return report, months, prev

    def reload(self, *_):
        report, months, prev = self._compute()
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
                        from .common import GREEN, RED
                        item.setForeground(i, (RED if (p > 0) == invert else GREEN))
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
        _do_export(self, kind, self.table(), f"synthese {self.period.label()}")


# ================================================================= Comparaison
class CompareTab(QWidget):
    changed = Signal()

    MODES = ["Mois vs mois précédent", "Mois vs même mois de l'année précédente",
             "Période vs même période de l'année précédente (N / N-1)", "Deux périodes libres"]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Comparer :"))
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        row.addWidget(self.mode)
        row.addStretch()
        for w in _export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf")):
            row.addWidget(w)
        lay.addLayout(row)
        self.pa = PeriodSelector(self, default="Dernier mois", label="Période A :")
        self.pb = PeriodSelector(self, default="Dernier mois", label="Période B (référence) :")
        r2 = QHBoxLayout()
        r2.addWidget(self.pa)
        r2.addStretch()
        lay.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(self.pb)
        r3.addStretch()
        lay.addLayout(r3)
        self.tree = ReportTree(self)
        self.tree.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.tree, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.pa.changed.connect(self._sync_b)
        self.pb.changed.connect(self.reload)
        self._mode_changed()

    def refresh(self):
        bounds = self.db.date_bounds()
        self.pa.set_bounds(*bounds)
        self.pb.set_bounds(*bounds)
        self._sync_b()

    def _mode_changed(self, *_):
        m = self.mode.currentIndex()
        self.pb.setEnabled(m == 3)
        if m in (0, 1):
            self.pa.preset.setCurrentText("Dernier mois")
        elif m == 2:
            self.pa.preset.setCurrentText("Année en cours")
        self._sync_b()

    def _sync_b(self, *_):
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
            self.pb.set_bounds(an.month_first_day(min(b[0], self.pb.min_month)), an.month_first_day(self.pb.max_month))
            self.pb.set_period(*b)
            self.pb.blockSignals(False)
        self.reload()

    def reload(self, *_):
        a, b = self.pa.period(), self.pb.period()
        if None in a or None in b:
            return
        self.report = an.compare(self.db, a, b)
        la, lb = an.period_label(*a), an.period_label(*b)
        self.headers = ["Catégorie", f"A : {la}", f"B : {lb}", "Écart A − B", "Écart %"]

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
            item.setForeground(4, item.foreground(3))

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
        t = TableData("Comparaison", self.MODES[self.mode.currentIndex()], self.headers,
                      [TEXT, MONEY, MONEY, MONEY, PCT])
        report_to_rows(t, self.report, lambda n: [n.values.get("A", 0), n.values.get("B", 0),
                                                  n.values.get("A", 0) - n.values.get("B", 0),
                                                  pct_change(n.values.get("A", 0), n.values.get("B", 0))])
        _do_export(self, kind, t, "comparaison")


# ====================================================================== Budget
class BudgetTab(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Budget de l'année :"))
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(int(an.current_month()[:4]))
        row.addWidget(self.year)
        copy_btn = QPushButton("Copier le budget de l'année précédente")
        copy_btn.clicked.connect(self._copy_prev)
        row.addWidget(copy_btn)
        row.addSpacing(20)
        self.period = PeriodSelector(self, default="Année en cours", label="Suivi sur :")
        row.addWidget(self.period)
        row.addStretch()
        for w in _export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf")):
            row.addWidget(w)
        lay.addLayout(row)
        hint = QLabel("Double-cliquez dans la colonne « Budget mensuel » pour saisir un montant (vide = pas de budget). "
                      "Le budget d'une catégorie sans montant propre est la somme de ses sous-catégories.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7F8C8D")
        lay.addWidget(hint)
        self.tree = ReportTree(self)
        self.tree.itemDoubleClicked.connect(self._edit)
        self.tree.itemChanged.connect(self._item_changed)
        lay.addWidget(self.tree, 1)
        self.year.valueChanged.connect(self.reload)
        self.period.changed.connect(self.reload)
        self._filling = False

    def refresh(self):
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        self.report = an.budget_report(self.db, start, end)
        budgets = self.db.budgets(self.year.value())
        self.months_n = len(an.month_range(start, end))
        self.headers = ["Catégorie", f"Budget mensuel {self.year.value()}", "Budget sur la période",
                        "Réalisé", "Écart (budget − réalisé)", "% consommé"]

        def writer(item, node):
            own = budgets.get(node.cat_id) if node.cat_id is not None and node.level > 0 else None
            is_unsplit = node.level == 2 and node.label.endswith("(sans sous-catégorie)")
            if node.cat_id is not None and node.level > 0 and not is_unsplit:
                item.setText(1, fmt_eur(own) if own is not None else "")
                item.setData(1, SORT_ROLE, own or 0)
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            b, r = node.values.get("budget", 0), node.values.get("reel", 0)
            set_money(item, 2, b)
            set_money(item, 3, r)
            if b:
                good_if_positive = node.kind != "revenu" and node.label != "Total revenus"
                diff = b - r
                set_money(item, 4, diff, colorize=True, invert=not good_if_positive, signed=True,
                          blank_zero=False)
                ratio = r / b
                item.setText(5, f"{ratio * 100:.0f} %")
                item.setData(5, SORT_ROLE, ratio)
                item.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                if good_if_positive:
                    from .common import GREEN, ORANGE, RED
                    item.setForeground(5, RED if ratio > 1 else (ORANGE if ratio > 0.9 else GREEN))

        self._filling = True
        self.tree.fill(self.report, self.headers, writer, expanded=True)
        self._filling = False

    def _edit(self, item, col):
        node = item.data(0, NODE_ROLE)
        if col == 1 and node is not None and item.flags() & Qt.ItemIsEditable:
            self.tree.editItem(item, 1)

    def _item_changed(self, item, col):
        if self._filling or col != 1:
            return
        node = item.data(0, NODE_ROLE)
        if node is None:
            return
        try:
            cents = parse_eur_input(item.text(1))
        except ValueError:
            error(self, "Montant invalide. Exemple : 350 ou 1 250,50")
            self.reload()
            return
        if cents is not None:
            cents = abs(cents)
        self.db.set_budget(node.cat_id, self.year.value(), cents)
        self.reload()
        self.changed.emit()

    def _copy_prev(self):
        y = self.year.value()
        if not self.db.budgets(y - 1):
            info(self, f"Aucun budget saisi pour {y - 1}.")
            return
        from .common import confirm
        if self.db.budgets(y) and not confirm(self, f"Remplacer le budget {y} par celui de {y - 1} ?"):
            return
        self.db.copy_budgets(y - 1, y)
        self.reload()

    def export(self, kind):
        budgets = self.db.budgets(self.year.value())
        t = TableData("Budget", f"Suivi {self.period.label()} — budget {self.year.value()}", self.headers,
                      [TEXT, MONEY, MONEY, MONEY, MONEY, RATIO])

        def values(n):
            b, r = n.values.get("budget", 0), n.values.get("reel", 0)
            own = budgets.get(n.cat_id) if n.level > 0 and n.cat_id is not None else None
            return [own, b, r, (b - r) if b else None, (r / b) if b else None]

        report_to_rows(t, self.report, values)
        _do_export(self, kind, t, f"budget {self.year.value()}")
